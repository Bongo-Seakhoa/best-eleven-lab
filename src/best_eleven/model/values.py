"""Value every delivery: run expectancy -> contest value -> opposition/context adjustment.

Fit groups pool scopes that share opponents: each international format and
gender is its own group; franchise and domestic T20 leagues of one gender are
pooled so a player's IPL and BBL records share one bowler/batter scale.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from .adjust import adjusted_values, codes, eb_lambda, fit
from .context import home_teams
from .frames import Warehouse
from .runvalue import (FAMILY_BALLS, RunExpectancy, delivery_values, fit_run_expectancy,
                       remaining_runs_cells, test_wicket_value)

RE_COLS = ["match_id", "inning", "super_over", "balls_rem", "legal_before", "wkts_before",
           "score_before", "runs_total"]
MIN_MATCHES_TO_ADJUST = 50
FULL_MEMBERS = {"Australia", "England", "South Africa", "India", "New Zealand", "Pakistan",
                "Sri Lanka", "West Indies", "Bangladesh", "Zimbabwe", "Afghanistan", "Ireland"}


def league_scopes(competitions: str | Path) -> dict[str, list[str]]:
    data = json.loads(Path(competitions).read_text(encoding="utf-8"))
    out = {"male": [], "female": []}
    for lg in data["leagues"]:
        out[lg["gender"]].append(lg["key"])
    return out


def fit_groups(competitions: str | Path) -> dict[str, list[str]]:
    lg = league_scopes(competitions)
    groups = {s: [s] for s in ("men-test", "men-odi", "men-t20i", "women-test", "women-odi", "women-t20i")}
    groups["men-club"] = lg["male"]
    groups["women-club"] = lg["female"]
    return groups


def fit_all_re(wh: Warehouse) -> dict[tuple[str, str], RunExpectancy]:
    m = wh.matches
    models = {}
    for fam in FAMILY_BALLS:
        for g in ("male", "female"):
            acc = []
            for s in m[(m["family"] == fam) & (m["gender"] == g)]["scope"].unique():
                d = wh.deliveries(s, RE_COLS)
                d = d[(d["family"] == fam) & (d["gender"] == g)]
                if len(d):
                    acc.append(remaining_runs_cells(d, fam))
            if not acc:
                continue
            cells = pd.concat(acc).groupby(["era", "u", "w"], as_index=False)[["n", "runs"]].sum()
            inn: dict = {}
            for c in acc:
                for k, v in c.attrs["innings"].items():
                    inn[k] = inn.get(k, 0) + v
            cells.attrs["innings"] = inn
            models[(fam, g)] = fit_run_expectancy(cells, fam, g)
    return models


def test_w_by_gender(wh: Warehouse) -> dict[str, pd.Series]:
    cols = ["runs_batter", "striker_out", "ns_out", "super_over"]
    out = {}
    for g, s in (("male", "men-test"), ("female", "women-test")):
        d = wh.deliveries(s, cols)
        w = test_wicket_value(d)
        if g == "female":  # 24 matches: one pooled value is steadier than yearly noise
            w = pd.Series(float(w.mean()), index=w.index)
        out[g] = w
    return out


def value_group(wh: Warehouse, group: str, scopes: list[str], re_models: dict,
                test_w: dict, home: pd.DataFrame) -> tuple[dict[str, pd.DataFrame], dict]:
    frames = []
    for s in scopes:
        if (wh.root / "deliveries" / f"{s}.parquet").exists():
            frames.append(wh.deliveries(s))
    if not frames:
        return {}, {}
    d = pd.concat(frames, ignore_index=True)
    for c in ("batting_team", "bowling_team", "scope", "family", "gender", "event", "format"):
        d[c] = d[c].astype(str)
    d = d[d["super_over"] == 0]
    parts = []
    for (fam, g), sub in d.groupby(["family", "gender"], sort=False):
        re = re_models.get((fam, g)) if fam != "multi" else None
        parts.append(delivery_values(sub, fam, re, test_w.get(g) if fam == "multi" else None))
    d = pd.concat(parts).sort_values(["match_id", "inning", "ordinal"]).reset_index(drop=True)

    # Whether each side is an ICC Full Member; lets selection ignore associate opposition.
    club = group.endswith("club")
    d["bowl_full"] = np.int8(1) if club else d["bowling_team"].isin(FULL_MEMBERS).astype(np.int8)
    d["bat_full"] = np.int8(1) if club else d["batting_team"].isin(FULL_MEMBERS).astype(np.int8)
    d = d.merge(home, on="match_id", how="left")
    ht = d["home_team"].astype(object)
    d["home"] = np.where(ht == d["batting_team"], 1, np.where(ht == d["bowling_team"], -1, 0)).astype(np.int8)
    inn_key = d["inning"].clip(upper=4 if group.endswith("test") else 2).astype(str)
    ctx = d["year"].astype(str) + "|" + d["phase"].astype(str) + "|" + inn_key + "|" + d["home"].astype(str)
    if group.endswith("club"):
        ctx = d["scope"] + "|" + ctx
    d["ctx"] = ctx

    faced = d["faced"].to_numpy() == 1
    n_matches = d["match_id"].nunique()
    meta = {"group": group, "scopes": scopes, "matches": int(n_matches), "deliveries": int(len(d))}
    bat_adj = np.zeros(len(d), dtype=np.float32)
    bowl_adj = np.zeros(len(d), dtype=np.float32)
    y = d["contest"].to_numpy(np.float64)
    if n_matches >= MIN_MATCHES_TO_ADJUST:
        sub = d.loc[faced]
        factors = {"batter": codes(sub["batter"])[0], "bowler": codes(sub["bowler"])[0],
                   "bat_team": codes(sub["batting_team"])[0], "bowl_team": codes(sub["bowling_team"])[0],
                   "ctx": codes(sub["ctx"])[0]}
        f = fit(y[faced], factors)
        ba, bo = adjusted_values(y[faced], factors, f)
        # Selection compares specialists, so the shrinkage used downstream is the
        # empirical-Bayes penalty among top-seven batters (tail-enders widen the
        # between-player spread and would make the penalty far too weak).
        top = (sub["batter_pos"] <= 7).to_numpy()
        lam_sel, _ = eb_lambda(ba[top].astype(np.float64), factors["batter"][top])
        bat_adj[faced], bowl_adj[faced] = ba, bo
        bt = pd.Series(f.coef["bowl_team"], index=pd.Categorical(sub["bowling_team"]).categories)
        meta.update({"adjusted": True, "mu": round(f.mu, 4), "lambda_bat": round(max(lam_sel, f.lam_bat), 1),
                     "lambda_bat_fit": round(f.lam_bat, 1),
                     "lambda_bowl": round(f.lam_bowl, 1), "sigma2": round(f.sigma2, 4),
                     "ctx_levels": int(factors["ctx"].max() + 1),
                     "bowling_unit_effect": {k: round(float(v), 4) for k, v in bt.sort_values().items()}})
    else:
        mu = float(y[faced].mean())
        bat_adj[faced] = y[faced] - mu
        bowl_adj[faced] = y[faced] - mu
        meta.update({"adjusted": False, "mu": round(mu, 4), "lambda_bat": 400.0, "lambda_bowl": 400.0})
    # Bowlers also carry wides and no-ball runs, centred on the year's average rate.
    ex = d["extras_cost"].to_numpy(np.float32)
    ex_mean = d.groupby("year")["extras_cost"].transform("mean").to_numpy(np.float32)
    d["bat_adj"] = bat_adj
    d["bowl_cost"] = bowl_adj + ex - ex_mean
    # Centre on an average Full-Member player facing Full-Member opposition so that
    # "runs added" reads against a recognisable reference rather than a pool
    # that includes associate sides.
    both = (d["bat_full"] == 1) & (d["bowl_full"] == 1)
    c_bat = float(d.loc[both & faced, "bat_adj"].mean())
    c_bowl = float(d.loc[both, "bowl_cost"].mean())
    d["bat_adj"] = (d["bat_adj"] - np.where(faced, c_bat, 0.0)).astype(np.float32)
    d["bowl_cost"] = (d["bowl_cost"] - c_bowl).astype(np.float32)
    meta.update({"centre_bat": round(c_bat, 4), "centre_bowl": round(c_bowl, 4)})
    keep = [c for c in d.columns if c not in ("team1", "team2", "city", "venue", "event_stage",
                                             "result", "winner", "start_date")]
    return {s: g.loc[:, keep] for s, g in d.groupby("scope")}, meta


def build_values(warehouse: str | Path, competitions: str | Path, out: str | Path,
                 log=print) -> dict:
    wh = Warehouse(warehouse)
    out = Path(out)
    (out / "values").mkdir(parents=True, exist_ok=True)
    re_models = fit_all_re(wh)
    test_w = test_w_by_gender(wh)
    home = home_teams(wh.matches)
    summary = {"run_expectancy": {f"{k[0]}-{k[1]}": m.to_json() for k, m in re_models.items()},
               "test_wicket_value": {g: {int(y): round(float(v), 2) for y, v in w.items()}
                                     for g, w in test_w.items()},
               "groups": {}}
    for group, scopes in fit_groups(competitions).items():
        parts, meta = value_group(wh, group, scopes, re_models, test_w, home)
        for s, frame in parts.items():
            frame.to_parquet(out / "values" / f"{s}.parquet", compression="zstd", index=False)
        summary["groups"][group] = meta
        log(f"valued {group}: " + str({k: v for k, v in meta.items() if k != "bowling_unit_effect"}))
    (out / "values_summary.json").write_text(json.dumps(summary), encoding="utf-8")
    return summary
