"""Additive season aggregates per (player, year, team, opposition class).

Everything the selector needs is a sum, so any year window, team filter or
recency weighting can be applied in the browser without re-running Python.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from .frames import Warehouse
from .values import FULL_MEMBERS

KEYS = ["player", "year", "team", "opp_full"]


def opponent_full(matches: pd.DataFrame) -> pd.DataFrame:
    """(match_id, team) -> opp_full: 1 when the opponent is a Full Member
    (always 1 outside international cricket)."""
    m = matches[["match_id", "team1", "team2", "team_type"]]
    a = m.rename(columns={"team1": "team", "team2": "opp"})
    b = m.rename(columns={"team2": "team", "team1": "opp"})
    x = pd.concat([a, b], ignore_index=True)
    x["opp_full"] = np.where(x["team_type"] == "international", x["opp"].isin(FULL_MEMBERS), True).astype(np.int8)
    return x[["match_id", "team", "opp_full"]]


def scope_aggregates(wh: Warehouse, scope: str, values_dir: Path, keepers: pd.DataFrame) -> pd.DataFrame:
    m = wh.matches
    ms = m[m["scope"] == scope][["match_id", "year"]]
    ids = set(ms["match_id"])
    opp = opponent_full(m[m["match_id"].isin(ids)])
    v = pd.read_parquet(values_dir / f"{scope}.parquet",
                        columns=["match_id", "inning", "batter", "bowler", "non_striker", "faced",
                                 "legal", "phase", "bat_adj", "bowl_cost", "ns_out", "ns_value"])

    # batting -------------------------------------------------------------
    bat = wh.table("batting")
    bat = bat[bat["match_id"].isin(ids) & (bat["super_over"] == 0)].copy()
    bat["team"] = bat["team"].astype(str)
    val_b = v[v["faced"] == 1].groupby(["match_id", "inning", "batter"])["bat_adj"].sum()
    val_ns = v[v["ns_out"] == 1].groupby(["match_id", "inning", "non_striker"])["ns_value"].sum()
    bat = bat.merge(val_b.rename("ba").reset_index().rename(columns={"batter": "player"}),
                    on=["match_id", "inning", "player"], how="left")
    bat = bat.merge(val_ns.rename("nsv").reset_index().rename(columns={"non_striker": "player"}),
                    on=["match_id", "inning", "player"], how="left")
    bat["ba"] = bat["ba"].fillna(0) + bat["nsv"].fillna(0)
    pos = bat["position"]
    bat = bat.assign(bi=1, no=1 - bat["out"], h50=((bat["runs"] >= 50) & (bat["runs"] < 100)).astype(int),
                     h100=(bat["runs"] >= 100).astype(int), p12=(pos <= 2).astype(int),
                     p3=(pos == 3).astype(int), p46=pos.between(4, 6).astype(int), p7=(pos >= 7).astype(int))
    bat = bat.merge(ms, on="match_id").merge(opp, on=["match_id", "team"])
    B = bat.groupby(KEYS).agg(bi=("bi", "sum"), no=("no", "sum"), r=("runs", "sum"), b=("balls", "sum"),
                              o=("out", "sum"), f4=("fours", "sum"), f6=("sixes", "sum"), d0=("dots", "sum"),
                              h50=("h50", "sum"), h100=("h100", "sum"), hs=("runs", "max"),
                              p12=("p12", "sum"), p3=("p3", "sum"), p46=("p46", "sum"), p7=("p7", "sum"),
                              ba=("ba", "sum"))

    # bowling -------------------------------------------------------------
    bw = wh.table("bowling")
    bw = bw[bw["match_id"].isin(ids) & (bw["super_over"] == 0)].copy()
    bw["team"] = bw["team"].astype(str)
    cost = v.groupby(["match_id", "inning", "bowler"])["bowl_cost"].sum().rename("wc").reset_index()
    ph = (v[v["legal"] == 1].groupby(["match_id", "inning", "bowler", "phase"]).size()
          .unstack(fill_value=0).reindex(columns=[0, 1, 2], fill_value=0))
    ph.columns = ["wp0", "wp1", "wp2"]
    bw = bw.merge(cost.rename(columns={"bowler": "player"}), on=["match_id", "inning", "player"], how="left")
    bw = bw.merge(ph.reset_index().rename(columns={"bowler": "player"}), on=["match_id", "inning", "player"], how="left")
    # Haul counts are per match (a Test has two bowling innings).
    hauls = bw.groupby(["match_id", "player"])["wickets"].sum().rename("mw").reset_index()
    bw = bw.merge(ms, on="match_id").merge(opp, on=["match_id", "team"])
    W = bw.groupby(KEYS).agg(wi=("balls", lambda s: int((s > 0).sum())), wb=("balls", "sum"),
                             wr=("conceded", "sum"), ww=("wickets", "sum"), wm=("maidens", "sum"),
                             wd=("dots", "sum"), wx=("wides", "sum"), wn=("noballs", "sum"),
                             wc=("wc", "sum"), wp0=("wp0", "sum"), wp1=("wp1", "sum"), wp2=("wp2", "sum"))
    hauls = hauls.merge(bw[["match_id", "player", "year", "team", "opp_full"]].drop_duplicates(["match_id", "player"]),
                        on=["match_id", "player"])
    hauls = hauls.assign(w3=(hauls["mw"] >= 3).astype(int), w5=(hauls["mw"] >= 5).astype(int))
    W = W.join(hauls.groupby(KEYS)[["w3", "w5"]].sum(), how="left")

    # fielding and keeping --------------------------------------------------
    wk = wh.table("wickets")
    wk = wk[wk["match_id"].isin(ids) & (wk["super_over"] == 0)]
    inn = wh.innings[["match_id", "inning", "bowling_team"]]
    wk = wk.merge(inn, on=["match_id", "inning"]).rename(columns={"bowling_team": "team"})
    wk["team"] = wk["team"].astype(str)
    kp = keepers[keepers["match_id"].isin(ids)].rename(columns={"keeper": "kid"})
    wk = wk.merge(kp[["match_id", "team", "kid"]], on=["match_id", "team"], how="left")
    rows = []
    caught = wk[(wk["kind"] == 1) & (wk["fielder1"] >= 0) & (wk["fielder1_sub"] == 0)]
    is_k = caught["fielder1"] == caught["kid"]
    rows.append(caught[~is_k].assign(player=caught["fielder1"], ct=1))
    rows.append(caught[is_k].assign(player=caught["fielder1"], kc=1))
    cb = wk[wk["kind"] == 5]
    rows.append(cb.assign(player=cb["bowler"], ct=1))
    st = wk[(wk["kind"] == 6) & (wk["fielder1"] >= 0)]
    rows.append(st.assign(player=st["fielder1"], st=1))
    ro = wk[wk["kind"] == 4]
    for f in ("fielder1", "fielder2"):
        r = ro[(ro[f] >= 0)]
        rows.append(r.assign(player=r[f], ro=1))
    F = pd.concat(rows, ignore_index=True)
    F = F.merge(ms, on="match_id").merge(opp, on=["match_id", "team"])
    for c in ("ct", "kc", "st", "ro"):
        if c not in F:
            F[c] = 0
    F = F.groupby(KEYS)[["ct", "kc", "st", "ro"]].sum()

    # appearances, keeping -----------------------------------------------------
    ap = wh.table("appearances")
    ap = ap[ap["match_id"].isin(ids)].copy()
    ap["team"] = ap["team"].astype(str)
    ap = ap.merge(kp[["match_id", "team", "kid"]], on=["match_id", "team"], how="left")
    ap["kp"] = (ap["player"] == ap["kid"]).astype(int)
    ap = ap.merge(ms, on="match_id").merge(opp, on=["match_id", "team"])
    A = ap.groupby(KEYS).agg(m=("match_id", "nunique"), kp=("kp", "sum"))

    out = A.join([B, W, F], how="outer").fillna(0)
    ints = [c for c in out.columns if c not in ("ba", "wc")]
    out[ints] = out[ints].astype(np.int32)
    out["ba"] = out["ba"].astype(np.float32)
    out["wc"] = out["wc"].astype(np.float32)
    return out.reset_index()


def build_aggregates(warehouse: str | Path, model_dir: str | Path, *, wiki_keepers: set[int] | None = None,
                     log=print) -> dict[str, pd.DataFrame]:
    from .context import keepers as infer_keepers
    wh = Warehouse(warehouse)
    model_dir = Path(model_dir)
    kp = infer_keepers(wh.table("wickets"), wh.table("appearances"), wh.innings, wiki_keepers)
    kp.to_parquet(model_dir / "keepers.parquet", index=False)
    out = {}
    (model_dir / "seasons").mkdir(parents=True, exist_ok=True)
    for f in sorted((model_dir / "values").glob("*.parquet")):
        scope = f.stem
        agg = scope_aggregates(wh, scope, model_dir / "values", kp)
        agg.to_parquet(model_dir / "seasons" / f"{scope}.parquet", index=False)
        out[scope] = agg
        log(f"aggregated {scope}: {len(agg)} rows, {agg['player'].nunique()} players")
    return out
