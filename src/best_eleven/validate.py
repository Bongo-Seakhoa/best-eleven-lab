"""Reconciliation and predictive checks against the real archive.

1. Margins: innings totals rebuilt from deliveries must reproduce every
   official winning margin (runs, innings-and-runs, wickets).
2. Careers: Cricsheet totals must agree with Wikipedia's career figures for
   players whose whole career lies inside ball-by-ball coverage.
3. Prediction: do opposition-adjusted ratings from one period predict a
   player's raw output in the next period better than raw figures do?
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

INTL_FMT = {"men-test": ("Test", "Test"), "men-odi": ("ODI", "ODI"), "men-t20i": ("T20I", "T20I")}


def margin_check(wh_dir: Path) -> dict:
    m = pd.read_parquet(wh_dir / "matches.parquet")
    inn = pd.read_parquet(wh_dir / "innings.parquet")
    inn = inn[inn["super_over"] == 0].copy()
    inn["batting_team"] = inn["batting_team"].astype(str)
    tot = inn.groupby(["match_id", "batting_team"])["runs"].sum().rename("runs").reset_index()
    m = m[(m["result"] == "win") & (m["method"] == "")]
    # By runs (all formats, including innings victories).
    r = m[(m["by_runs"] >= 0) | (m["innings_runs"] >= 0)].copy()
    r["loser"] = np.where(r["winner"] == r["team1"], r["team2"], r["team1"])
    r = r.merge(tot.rename(columns={"batting_team": "winner", "runs": "w_runs"}), on=["match_id", "winner"])
    r = r.merge(tot.rename(columns={"batting_team": "loser", "runs": "l_runs"}), on=["match_id", "loser"])
    r["margin"] = np.where(r["by_runs"] >= 0, r["by_runs"], r["innings_runs"])
    r_ok = (r["w_runs"] - r["l_runs"] == r["margin"])
    # By wickets: the chasing side's final innings lost 10 - margin wickets.
    w = m[m["by_wickets"] >= 0]
    last = inn.sort_values("inning").groupby("match_id").tail(1)
    w = w.merge(last[["match_id", "batting_team", "wickets", "absent_hurt"]], on="match_id")
    w = w[w["batting_team"] == w["winner"]]
    w_ok = (w["wickets"] == 10 - w["by_wickets"])
    return {
        "name": "Winning margins rebuilt from deliveries",
        "passed": bool(r_ok.mean() > 0.995 and w_ok.mean() > 0.99),
        "summary": f"runs margins {r_ok.mean():.2%} of {len(r):,}; wickets margins {w_ok.mean():.2%} of {len(w):,}",
        "runs": {"checked": int(len(r)), "exact": int(r_ok.sum())},
        "wickets": {"checked": int(len(w)), "exact": int(w_ok.sum())},
        "runs_mismatches": r.loc[~r_ok, ["match_id", "winner", "w_runs", "l_runs", "margin"]].head(20).to_dict("records"),
        "wickets_mismatches": w.loc[~w_ok, ["match_id", "winner", "wickets", "by_wickets", "absent_hurt"]].head(20).to_dict("records"),
    }


def career_check(model_dir: Path, wh_dir: Path, reference: Path) -> dict:
    """Two views. Strict: men's Test players from sides that have never met
    Afghanistan in a Test (Cricsheet withholds those matches), whose Wikipedia
    figures were updated within 60 days of the data end; these must agree
    exactly. Broad: every player whose career lies inside coverage, reported
    for context (gaps there come from withheld matches and stale infoboxes)."""
    path = reference / "players_wiki.csv"
    name = "Career totals vs Wikipedia"
    if not path.exists():
        return {"name": name, "passed": False, "summary": "players_wiki.csv missing"}
    wiki = pd.read_csv(path, dtype=str, keep_default_na=False)
    wiki = wiki[(wiki["cricsheet_id"] != "") & (wiki["career_json"] != "")].drop_duplicates("cricsheet_id")
    wiki["stamp"] = pd.to_datetime(wiki["stats_as_of"], errors="coerce", dayfirst=True)
    players = pd.read_parquet(wh_dir / "players.parquet")[["player", "id"]]
    data_end = pd.Timestamp(pd.read_parquet(wh_dir / "matches.parquet")["end_date"].max())
    frames = []
    for scope, (fmt, key) in INTL_FMT.items():
        s = pd.read_parquet(model_dir / "seasons" / f"{scope}.parquet")
        start = int(s["year"].min())
        nat = s.groupby(["player", "team"])["m"].sum().reset_index().sort_values("m").drop_duplicates("player", keep="last")
        g = s.groupby("player").agg(first=("year", "min"), m=("m", "sum"), r=("r", "sum"), ww=("ww", "sum"))
        g = g.join(nat.set_index("player")["team"].rename("nat"))
        g = g[g["first"] >= start + 3].join(players.set_index("player"))
        g = g.merge(wiki[["cricsheet_id", "career_json", "stamp"]], left_on="id", right_on="cricsheet_id")
        c = g["career_json"].map(lambda x: json.loads(x).get(key) or {})
        g["wk_m"], g["wk_r"], g["wk_w"] = (c.map(lambda d: d.get("matches")), c.map(lambda d: d.get("runs") or 0),
                                           c.map(lambda d: d.get("wickets") or 0))
        g = g.dropna(subset=["wk_m"])
        g["format"] = fmt
        frames.append(g)
    df = pd.concat(frames, ignore_index=True)
    exact = (df["m"] == df["wk_m"]) & (df["r"] == df["wk_r"]) & (df["ww"] == df["wk_w"])
    strict = ((df["format"] == "Test") & df["nat"].isin(["Australia", "England", "South Africa", "Pakistan"])
              & (df["stamp"] >= data_end - pd.Timedelta(days=60)))
    broad = {fmt: {"players": int((df["format"] == fmt).sum()),
                   "exact": round(float(exact[df["format"] == fmt].mean()), 4),
                   "cricsheet_fewer": round(float((df["m"] < df["wk_m"])[df["format"] == fmt].mean()), 4),
                   "cricsheet_more": round(float((df["m"] > df["wk_m"])[df["format"] == fmt].mean()), 4)}
             for fmt in ("Test", "ODI", "T20I")}
    rate = float(exact[strict].mean()) if strict.any() else 0.0
    return {"name": name, "passed": bool(strict.sum() >= 50 and rate >= 0.98),
            "summary": (f"strict set: {int(strict.sum())} Test players, {rate:.1%} exact on matches, runs and wickets; "
                        f"all players: exact {broad['Test']['exact']:.0%} Tests, {broad['ODI']['exact']:.0%} ODIs, "
                        f"{broad['T20I']['exact']:.0%} T20Is (Afghanistan matches withheld, infoboxes lag)"),
            "strict": {"players": int(strict.sum()), "exact": round(rate, 4),
                       "mismatches": df.loc[strict & ~exact, ["id", "m", "wk_m", "r", "wk_r", "ww", "wk_w"]].head(20).to_dict("records")},
            "broad": broad}


def predictive_check(model_dir: Path, split: int = 2021) -> dict:
    """Earlier-period rating vs later-period raw output, per format."""
    summary = json.loads((model_dir / "values_summary.json").read_text(encoding="utf-8"))["groups"]
    res = {}
    for scope in ("men-test", "men-odi", "men-t20i", "ipl"):
        g = summary["men-club" if scope == "ipl" else scope]
        lam = g["lambda_bat"]
        d = pd.read_parquet(model_dir / "values" / f"{scope}.parquet",
                            columns=["batter", "year", "faced", "contest", "bat_adj", "runs_batter"])
        d = d[d["faced"] == 1]
        a = d[d["year"].between(split - 5, split)].groupby("batter").agg(n=("faced", "size"), raw=("contest", "sum"),
                                                                     adj=("bat_adj", "sum"), runs=("runs_batter", "sum"))
        b = d[d["year"] > split].groupby("batter").agg(n=("faced", "size"), raw=("contest", "sum"))
        j = a.join(b, rsuffix="_next", how="inner")
        j = j[(j["n"] >= 300) & (j["n_next"] >= 300)]
        if len(j) < 30:
            continue
        target = j["raw_next"] / j["n_next"]
        preds = {"raw value per ball": j["raw"] / j["n"],
                 "strike rate": j["runs"] / j["n"],
                 "adjusted, shrunk (this model)": j["adj"] / (j["n"] + lam)}
        res[scope] = {"players": int(len(j)),
                      "spearman": {k: round(float(v.corr(target, method="spearman")), 3) for k, v in preds.items()}}
    better = [v["spearman"]["adjusted, shrunk (this model)"] >= v["spearman"]["raw value per ball"] for v in res.values()]
    return {"name": "Out-of-sample: earlier rating vs later output", "passed": bool(better and all(better)),
            "summary": "; ".join(f"{k}: adjusted {v['spearman']['adjusted, shrunk (this model)']:.2f} vs raw "
                                 f"{v['spearman']['raw value per ball']:.2f} ({v['players']} batters)"
                                 for k, v in res.items()),
            "split_year": split, "scopes": res}


VERSUS_CHECK = "XI vs XI: held-out win chances beat a coin flip"


def versus_check(calibration: dict, min_held_out: int = 200) -> dict:
    """XI vs XI win chances on matches after the fitting years. Every calibrated
    group with at least `min_held_out` such matches must beat its naive forecast
    on Brier score: a coin flip, or for Tests the training years' draw rate with
    decisive results split evenly. Recorded by the calibration step, which runs
    after export because it rates players from the exported scopes."""
    judged = {k: v for k, v in calibration.items() if v["nTest"] >= min_held_out}
    beat = {k: v["brier"] < v["brierBaseline"] for k, v in judged.items()}
    parts = [f"{v['label']} {v['brier']:.3f} vs {v['brierBaseline']:.3f} ({v['nTest']} matches)"
             for k, v in judged.items()]
    small = [v["label"] for v in calibration.values() if v["nTest"] < min_held_out]
    summary = ("Brier, model vs naive: " + "; ".join(parts) if parts
               else f"no calibrated group has {min_held_out} held-out matches")
    if small:
        summary += f". Too few held-out matches to judge: {', '.join(small)}"
    return {"name": VERSUS_CHECK, "passed": bool(judged) and all(beat.values()), "summary": summary,
            "min_held_out": min_held_out,
            "groups": {k: {"label": v["label"], "held_out": v["nTest"], "brier": v["brier"],
                           "brier_baseline": v["brierBaseline"], "log_loss": v["logLoss"],
                           "log_loss_baseline": v["logLossBaseline"], "accuracy": v["accuracy"],
                           "judged": k in judged} for k, v in calibration.items()}}


def run_checks(warehouse: str | Path, model_dir: str | Path, reference: str | Path) -> dict:
    wh, md, ref = Path(warehouse), Path(model_dir), Path(reference)
    from .model.priors import debut_validation
    checks = [margin_check(wh), career_check(md, wh, ref), predictive_check(md), debut_validation(wh, md)]
    fam = md / "bowler_family_metrics.json"
    if fam.exists():
        f = json.loads(fam.read_text(encoding="utf-8"))
        checks.append({"name": "Bowling-type classifier (5-fold CV)", "passed": f["cv_confident_accuracy"] >= 0.9,
                       "summary": f"accuracy {f['cv_accuracy']:.1%}, AUC {f['cv_auc']:.3f}; "
                                  f"confident labels {f['cv_confident_coverage']:.0%} at {f['cv_confident_accuracy']:.1%}",
                       **f})
    report = {"checks": checks}
    (md / "validation.json").write_text(json.dumps(report, indent=1, default=str), encoding="utf-8")
    return report
