"""Player profiles: matchups, phases, dismissal mechanics and field plans.

Every split uses the full delivery exposure (all balls faced or bowled), never
dismissals alone, so a batter who is caught often in one region but scores
heavily against the same bowlers is not mislabelled as weak there. Values are
the opposition-adjusted run values from values.py: a batter's figure against a
bowling type is measured relative to what an average batter did against those
same bowlers in the same phase, era and conditions.

A split is flagged as a strength or weakness only when it differs from the
player's own overall level by more than 1.96 standard errors and has enough
balls. With several splits per player some flags will be chance; the site says
so next to them.
"""
from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pandas as pd

from .archetypes import CLASS_LABELS, GROUPS

PHASE_LABELS = {"multi": ["New ball (overs 1-20)", "Overs 21-80", "Second new ball (80+)"],
                "fifty": ["Powerplay (1-10)", "Middle (11-40)", "Death (41-50)"],
                "t20": ["Powerplay (1-6)", "Middle (7-15)", "Death (16-20)"],
                "hundred": ["Powerplay (1-25)", "Middle (26-75)", "Death (76-100)"]}
MIN_SPLIT = {"multi": 300, "fifty": 150, "t20": 90, "hundred": 75}
MIN_MATCHUP = {"multi": 60, "fifty": 30, "t20": 18, "hundred": 15}
MODES = {"keeper": "Caught behind (keeper)", "field": "Caught in the field", "bowled": "Bowled",
         "lbw": "LBW", "stumped": "Stumped", "cb": "Caught & bowled", "runout": "Run out"}
POS_BANDS = [(1, 3, "Top order (1-3)"), (4, 6, "Middle order (4-6)"), (7, 8, "Lower order (7-8)"),
             (9, 11, "Tail (9-11)")]
Z = 1.96

VALUE_COLS = ["match_id", "inning", "batter", "bowler", "non_striker", "faced", "legal", "phase",
              "runs_batter", "four", "six", "striker_out", "striker_kind", "fielder", "bowler_wkt",
              "conceded", "bat_adj", "bowl_cost", "batter_pos", "bowling_team", "family", "contest"]


def _r(x, nd=2):
    if x is None or (isinstance(x, float) and not math.isfinite(x)):
        return None
    return round(float(x), nd)


def load_scope(values_dir: Path, scope: str, keepers: pd.DataFrame, bowler_group: pd.Series,
               bowler_family: pd.Series, hand: pd.Series) -> pd.DataFrame:
    d = pd.read_parquet(values_dir / f"{scope}.parquet", columns=VALUE_COLS)
    d["bowling_team"] = d["bowling_team"].astype(str)
    kp = keepers.rename(columns={"team": "bowling_team", "keeper": "kid"})[["match_id", "bowling_team", "kid"]]
    d = d.merge(kp, on=["match_id", "bowling_team"], how="left")
    k = d["striker_kind"]
    out = d["striker_out"] == 1
    d["m_keeper"] = (out & (k == 1) & (d["fielder"] == d["kid"])).astype(np.int8)
    d["m_field"] = (out & (k == 1) & (d["fielder"] != d["kid"])).astype(np.int8)
    d["m_bowled"] = (out & (k == 2)).astype(np.int8)
    d["m_lbw"] = (out & (k == 3)).astype(np.int8)
    d["m_stumped"] = (out & (k == 6)).astype(np.int8)
    d["m_cb"] = (out & (k == 5)).astype(np.int8)
    d["m_runout"] = (out & (k == 4)).astype(np.int8)
    d["dot"] = ((d["faced"] == 1) & (d["runs_batter"] == 0)).astype(np.int8)
    d["rot"] = d["runs_batter"].between(1, 3).astype(np.int8)
    g = d["bowler"].map(bowler_group)
    fam = d["bowler"].map(bowler_family).fillna("")
    g = g.fillna(fam.map({"pace": "Pace (type not recorded)", "spin": "Spin (type not recorded)"}))
    d["bgroup"] = g.fillna("Unclassified")
    d["bfam"] = fam
    d["bhand"] = d["batter"].map(hand).fillna("")
    pos = d["batter_pos"]
    d["posband"] = np.select([pos <= 3, pos <= 6, pos <= 8], [0, 1, 2], 3).astype(np.int8)
    return d


SUMS = {"balls": ("faced", "sum"), "runs": ("runs_batter", "sum"), "outs": ("striker_out", "sum"),
        "adj": ("bat_adj", "sum"), "f4": ("four", "sum"), "f6": ("six", "sum"), "dots": ("dot", "sum"),
        "rot": ("rot", "sum"), **{f"m_{k}": (f"m_{k}", "sum") for k in MODES}}
BOWL_SUMS = {"balls": ("legal", "sum"), "runs": ("conceded", "sum"), "wkts": ("bowler_wkt", "sum"),
             "cost": ("bowl_cost", "sum"), "f4": ("four", "sum"), "f6": ("six", "sum"), "dots": ("dot", "sum"),
             **{f"m_{k}": (f"m_{k}", "sum") for k in MODES if k != "runout"}}


def _split_rows(g: pd.DataFrame, label_of, overall_rate: float, sigma2: float, lam: float, family: str,
                bowling: bool = False) -> list[dict]:
    rows = []
    for key, r in g.iterrows():
        n = r["balls"]
        if n <= 0:
            continue
        val = -r["cost"] if bowling else r["adj"]
        rate = val / (n + lam)
        z = (val / n - overall_rate) / math.sqrt(sigma2 / n)
        flag = ""
        if n >= MIN_SPLIT[family]:
            flag = "strength" if z > Z else "weakness" if z < -Z else ""
        if bowling:
            row = {"group": label_of(key), "balls": int(n), "runs": int(r["runs"]), "wkts": int(r["wkts"]),
                   "avg": _r(r["runs"] / r["wkts"]) if r["wkts"] else None,
                   "econ": _r(6 * r["runs"] / n), "sr": _r(n / r["wkts"], 1) if r["wkts"] else None}
        else:
            row = {"group": label_of(key), "balls": int(n), "runs": int(r["runs"]), "outs": int(r["outs"]),
                   "avg": _r(r["runs"] / r["outs"]) if r["outs"] else None, "sr": _r(100 * r["runs"] / n, 1)}
        row.update({"dotPct": _r(100 * r["dots"] / n, 1), "bdryPct": _r(100 * (r["f4"] + r["f6"]) / n, 1),
                    "value": _r(100 * rate), "lo": _r(100 * (val / n - Z * math.sqrt(sigma2 / n))),
                    "hi": _r(100 * (val / n + Z * math.sqrt(sigma2 / n))), "z": _r(z), "flag": flag})
        rows.append(row)
    return rows


def _shrunk_rate(k, n, peer, strength=400.0):
    return (k + strength * peer) / (n + strength)


# --------------------------------------------------------------- field plans
# Named positions only; the site places them on the rendered ground in metres
# (site/assets/js/ui/charts.js), so geometry lives in one place.
OUTFIELD_CAP = {"multi": [9, 9, 9], "fifty": [2, 4, 5], "t20": [2, 5, 5], "hundred": [2, 5, 5]}


def field_plan(rates: dict, peer: dict, family: str, bowl_family: str, phase: int,
               hand: str = "right", perspective: str = "batter") -> dict:
    """Translate measured per-ball rates into a nine-fielder plan.

    rates/peer: per-ball rates for keeper (edges caught behind), field (caught
    elsewhere), straight (bowled+lbw), stumped, four, six, rot (1-3 runs), dot.
    """
    idx = {k: (rates[k] / peer[k] if peer.get(k) else 1.0) for k in rates}
    cap = OUTFIELD_CAP[family][phase]
    why = []
    spin = bowl_family == "spin"
    test = family == "multi"
    if test:
        catchers = 2 if spin else 4
        deep = 2
    else:
        catchers = {0: 2, 1: 1, 2: 0}[phase] if not spin else {0: 1, 1: 1, 2: 0}[phase]
        deep = min(cap, {0: 2, 1: 4, 2: 5}[phase])
    if idx["keeper"] >= 1.2:
        catchers += 1; why.append(("keeper", idx["keeper"], "an extra catcher behind the wicket"))
    elif idx["keeper"] <= 0.8 and catchers > 0:
        catchers -= 1; why.append(("keeper", idx["keeper"], "one fewer slip; edges behind are rare"))
    if test and idx["field"] >= 1.2:
        catchers += 1; why.append(("field", idx["field"], "a bat-pad or gully catcher"))
    bdry = (rates["four"] + rates["six"]) / max(peer["four"] + peer["six"], 1e-9)
    if bdry >= 1.15 and deep < cap:
        deep += 1; why.append(("boundary", bdry, "another boundary rider"))
    elif bdry <= 0.85 and deep > (0 if test else 1):
        deep -= 1; why.append(("boundary", bdry, "a boundary rider brought into the ring"))
    if not test and idx["field"] >= 1.2 and deep < cap:
        deep += 1; why.append(("field", idx["field"], "a deep catcher for the mis-hit"))
    if idx["rot"] >= 1.15:
        why.append(("rot", idx["rot"], "ring fielders saving one"))
    if idx["straight"] >= 1.2:
        why.append(("straight", idx["straight"], "attack the stumps; straight mid-on and mid-off"))
    if spin and idx["stumped"] >= 1.3:
        why.append(("stumped", idx["stumped"], "keeper up, toss it up; long-on and long-off back"))
    catchers = max(0, min(catchers, 9 - deep))
    ring = 9 - catchers - deep
    close_order = (["1st slip", "Short leg", "Silly point", "Leg slip", "2nd slip", "Short mid-wicket"] if spin
                   else ["1st slip", "2nd slip", "Gully", "3rd slip", "Short leg", "4th slip", "Leg slip"])
    if idx["field"] >= 1.2 and not spin and test:
        close_order = ["1st slip", "2nd slip", "Gully", "Short leg", "3rd slip", "4th slip", "Leg slip"]
    ring_order = ["Mid-on", "Mid-off", "Cover", "Point", "Mid-wicket", "Square leg", "Extra cover",
                  "Short fine leg", "Short third man"]
    if spin:
        deep_order = ["Long-on", "Deep mid-wicket", "Long-off", "Deep square leg", "Deep cover", "Deep point",
                      "Cow corner", "Fine leg", "Third man"]
    else:
        deep_order = ["Fine leg", "Third man", "Deep square leg", "Deep point", "Long-on", "Long-off",
                      "Deep mid-wicket", "Deep cover", "Cow corner"]
    if rates["six"] / max(peer["six"], 1e-9) >= 1.25:
        deep_order = ["Long-on", "Deep mid-wicket", "Cow corner"] + [p for p in deep_order
                                                                     if p not in ("Long-on", "Deep mid-wicket", "Cow corner")]
    if spin and idx["stumped"] >= 1.3:
        deep_order = ["Long-on", "Long-off"] + [p for p in deep_order if p not in ("Long-on", "Long-off")]
    names = close_order[:catchers] + ring_order[:ring] + deep_order[:deep]
    pos = [{"name": n, "zone": "close" if n in close_order else "ring" if n in ring_order else "deep"} for n in names]
    pos.insert(0, {"name": "Wicketkeeper", "zone": "keeper"})
    return {"positions": pos, "counts": {"close": catchers, "ring": ring, "deep": deep},
            "outfieldCap": cap if not test else None,
            "reasons": [{"signal": s, "index": _r(v), "action": a} for s, v, a in why],
            "indices": {k: _r(v) for k, v in idx.items()},
            "hand": hand, "phase": phase, "bowling": bowl_family, "perspective": perspective}


def _rates(r: pd.Series, n: float, outs_key: str = "outs") -> dict:
    n = max(n, 1)
    return {"keeper": r["m_keeper"] / n, "field": r["m_field"] / n, "straight": (r["m_bowled"] + r["m_lbw"]) / n,
            "stumped": r["m_stumped"] / n, "four": r["f4"] / n, "six": r["f6"] / n,
            "rot": r.get("rot", 0) / n, "dot": r["dots"] / n}


def scope_profiles(d: pd.DataFrame, family: str, sigma2: float, lam_bat: float, lam_bowl: float,
                   names: pd.Series, hands: pd.Series, bowler_family: pd.Series,
                   min_balls: int, ids: pd.Series | None = None) -> dict[int, dict]:
    """Batting and bowling profile blocks for every qualifying player in one scope."""
    labels = PHASE_LABELS[family]
    faced = d[d["faced"] == 1]
    profiles: dict[int, dict] = {}

    # Peer baselines: every batter in the scope, overall and per bowling family.
    peer_tot = faced[[src for src, _ in SUMS.values()]].sum()
    peer_fam_all = faced[faced["bfam"] != ""].groupby("bfam").agg(**SUMS)

    # ------------------------------------------------------------- batting
    bat_tot = faced.groupby("batter").agg(**SUMS)
    bat_tot = bat_tot[bat_tot["balls"] >= min_balls]
    keep = set(bat_tot.index)
    fb = faced[faced["batter"].isin(keep)]
    by_g = fb.groupby(["batter", "bgroup"]).agg(**SUMS)
    by_p = fb.groupby(["batter", "phase"]).agg(**SUMS)
    by_fam = fb[fb["bfam"] != ""].groupby(["batter", "bfam"]).agg(**SUMS)
    by_b = fb.groupby(["batter", "bowler"]).agg(**SUMS)
    by_b = by_b[by_b["balls"] >= MIN_MATCHUP[family]]
    for p, tot in bat_tot.iterrows():
        n = tot["balls"]
        overall = tot["adj"] / n
        block = {"balls": int(n), "runs": int(tot["runs"]), "outs": int(tot["outs"]),
                 "avg": _r(tot["runs"] / tot["outs"]) if tot["outs"] else None,
                 "sr": _r(100 * tot["runs"] / n, 1), "value": _r(100 * tot["adj"] / (n + lam_bat)),
                 "dotPct": _r(100 * tot["dots"] / n, 1), "bdryPct": _r(100 * (tot["f4"] + tot["f6"]) / n, 1)}
        g = by_g.loc[p] if p in by_g.index.get_level_values(0) else pd.DataFrame()
        block["vsBowling"] = sorted(_split_rows(g, str, overall, sigma2, lam_bat, family),
                                    key=lambda r: -r["balls"]) if len(g) else []
        ph = by_p.loc[p] if p in by_p.index.get_level_values(0) else pd.DataFrame()
        block["byPhase"] = _split_rows(ph, lambda k: labels[int(k)], overall, sigma2, lam_bat, family) if len(ph) else []
        modes = []
        for k, lab in MODES.items():
            peer_rate = peer_tot[f"m_{k}"] / peer_tot["faced"]
            mine = _shrunk_rate(tot[f"m_{k}"], n, peer_rate)
            modes.append({"mode": lab, "count": int(tot[f"m_{k}"]), "per1000": _r(1000 * tot[f"m_{k}"] / n),
                          "peerPer1000": _r(1000 * peer_rate), "index": _r(mine / peer_rate if peer_rate else None)})
        block["dismissals"] = modes
        plans = {}
        for fam in ("pace", "spin"):
            if (p, fam) not in by_fam.index:
                continue
            r = by_fam.loc[(p, fam)]
            if r["balls"] < MIN_SPLIT[family]:
                continue
            pr = peer_fam_all.loc[fam]
            peer = _rates(pr, pr["balls"])
            mine = {k: _shrunk_rate(v * r["balls"], r["balls"], peer[k]) for k, v in _rates(r, r["balls"]).items()}
            phase = 0 if family == "multi" and fam == "pace" else 1   # new ball in Tests, middle overs otherwise
            plans[fam] = field_plan(mine, peer, family, fam, phase, hands.get(p, "right") or "right") | {
                "balls": int(r["balls"])}
        block["fieldPlans"] = plans
        if len(by_b) and p in by_b.index.get_level_values(0):
            mb = by_b.loc[p].copy()
            mb["avg"] = mb["runs"] / mb["outs"].replace(0, np.nan)
            mb["sr"] = 100 * mb["runs"] / mb["balls"]
            top = mb.sort_values("balls", ascending=False).head(14)
            block["bowlers"] = [{"id": ids.get(b, "") if ids is not None else int(b), "name": names.get(b, ""), "balls": int(r["balls"]),
                                 "runs": int(r["runs"]), "outs": int(r["outs"]),
                                 "avg": _r(r["avg"]), "sr": _r(r["sr"], 1),
                                 "value": _r(100 * r["adj"] / (r["balls"] + lam_bat))} for b, r in top.iterrows()]
        profiles.setdefault(p, {})["batting"] = block

    # ------------------------------------------------------------- bowling
    bw = d
    bw_tot = bw.groupby("bowler").agg(**BOWL_SUMS)
    bw_tot = bw_tot[bw_tot["balls"] >= min_balls]
    keepb = set(bw_tot.index)
    bb = bw[bw["bowler"].isin(keepb)]
    tempo = _tempo(faced)
    bb = bb.assign(tempo=bb["batter"].map(tempo).fillna(1).astype(int))
    by_hand = bb[bb["bhand"] != ""].groupby(["bowler", "bhand"]).agg(**BOWL_SUMS)
    by_pos = bb.groupby(["bowler", "posband"]).agg(**BOWL_SUMS)
    by_tempo = bb.groupby(["bowler", "tempo"]).agg(**BOWL_SUMS)
    by_ph = bb.groupby(["bowler", "phase"]).agg(**BOWL_SUMS)
    by_bat = bb.groupby(["bowler", "batter"]).agg(**BOWL_SUMS)
    by_bat = by_bat[by_bat["balls"] >= MIN_MATCHUP[family]]
    peer_b = bw.groupby("bfam").agg(**BOWL_SUMS)
    tempo_lab = {0: "Anchors (slowest third)", 1: "Balanced", 2: "Aggressors (fastest third)"}
    for p, tot in bw_tot.iterrows():
        n = tot["balls"]
        overall = -tot["cost"] / n
        block = {"balls": int(n), "runs": int(tot["runs"]), "wkts": int(tot["wkts"]),
                 "avg": _r(tot["runs"] / tot["wkts"]) if tot["wkts"] else None,
                 "econ": _r(6 * tot["runs"] / n), "sr": _r(n / tot["wkts"], 1) if tot["wkts"] else None,
                 "value": _r(-100 * tot["cost"] / (n + lam_bowl)),
                 "dotPct": _r(100 * tot["dots"] / n, 1), "bdryPct": _r(100 * (tot["f4"] + tot["f6"]) / n, 1)}
        lv0 = lambda frame: frame.loc[p] if p in frame.index.get_level_values(0) else pd.DataFrame()
        block["vsHand"] = _split_rows(lv0(by_hand), lambda k: f"{str(k).title()}-handers", overall, sigma2,
                                      lam_bowl, family, bowling=True)
        block["vsPosition"] = _split_rows(lv0(by_pos), lambda k: POS_BANDS[int(k)][2], overall, sigma2,
                                          lam_bowl, family, bowling=True)
        block["vsTempo"] = _split_rows(lv0(by_tempo), lambda k: tempo_lab[int(k)], overall, sigma2,
                                       lam_bowl, family, bowling=True)
        block["byPhase"] = _split_rows(lv0(by_ph), lambda k: labels[int(k)], overall, sigma2, lam_bowl,
                                       family, bowling=True)
        fam = bowler_family.get(p, "")
        w = max(tot["wkts"], 1)
        pr = peer_b.loc[fam] if fam in peer_b.index else peer_b.sum()
        modes = []
        for k, lab in MODES.items():
            if k == "runout":
                continue
            peer_share = pr[f"m_{k}"] / max(pr["wkts"], 1)
            modes.append({"mode": lab, "count": int(tot[f"m_{k}"]), "share": _r(100 * tot[f"m_{k}"] / w, 1),
                          "peerShare": _r(100 * peer_share, 1),
                          "per1000": _r(1000 * tot[f"m_{k}"] / n),
                          "peerPer1000": _r(1000 * pr[f"m_{k}"] / max(pr["balls"], 1))})
        block["wickets"] = modes
        if fam:
            peer = _rates(pr.rename({"wkts": "outs"}).reindex(pr.index.union(["rot"]), fill_value=0), pr["balls"])
            mine_raw = _rates(tot.reindex(tot.index.union(["rot"]), fill_value=0), n)
            mine = {k: _shrunk_rate(v * n, n, peer[k]) for k, v in mine_raw.items()}
            mine["rot"] = peer["rot"] = 1.0
            block["fieldPlan"] = field_plan(mine, peer, family, fam, 1 if family != "multi" else 0,
                                            "right", perspective="bowler") | {"balls": int(n)}
        mb = lv0(by_bat)
        if len(mb):
            mb = mb.copy()
            top = mb.sort_values("balls", ascending=False).head(14)
            block["batters"] = [{"id": ids.get(b, "") if ids is not None else int(b), "name": names.get(b, ""), "balls": int(r["balls"]),
                                 "runs": int(r["runs"]), "wkts": int(r["wkts"]),
                                 "avg": _r(r["runs"] / r["wkts"]) if r["wkts"] else None,
                                 "econ": _r(6 * r["runs"] / r["balls"]),
                                 "value": _r(-100 * r["cost"] / (r["balls"] + lam_bowl))}
                                for b, r in top.iterrows()]
        profiles.setdefault(p, {})["bowling"] = block
    return profiles


def _tempo(faced: pd.DataFrame) -> pd.Series:
    """Batter tempo tercile by strike rate within their usual batting band."""
    g = faced.groupby("batter").agg(balls=("faced", "sum"), runs=("runs_batter", "sum"), pos=("batter_pos", "median"))
    g = g[g["balls"] >= 120]
    g["band"] = np.select([g["pos"] <= 3, g["pos"] <= 6, g["pos"] <= 8], [0, 1, 2], 3)
    g["sr"] = g["runs"] / g["balls"]
    g["tempo"] = g.groupby("band")["sr"].transform(lambda s: pd.qcut(s.rank(method="first"), 3, labels=False)
                                                   if len(s) >= 3 else 1)
    return g["tempo"]


# ------------------------------------------------------------------ assembly
PROFILE_MIN_BALLS = {"multi": 300, "fifty": 150, "t20": 90, "hundred": 75}
SEASON_COLS = ["m", "r", "b", "o", "ba", "wb", "wr", "ww", "wc", "h50", "h100", "bi", "ct", "kc", "st"]


def season_trend(seasons: pd.DataFrame, lam_bat: float, lam_bowl: float) -> dict[int, list]:
    g = seasons.groupby(["player", "year"])[SEASON_COLS].sum().reset_index()
    out: dict[int, list] = {}
    for r in g.itertuples(index=False):
        out.setdefault(r.player, []).append({
            "y": int(r.year), "m": int(r.m), "inns": int(r.bi), "runs": int(r.r), "balls": int(r.b),
            "avg": _r(r.r / r.o) if r.o else None, "sr": _r(100 * r.r / r.b, 1) if r.b else None,
            "h100": int(r.h100), "h50": int(r.h50),
            "batValue": _r(100 * r.ba / (r.b + lam_bat)) if r.b else None,
            "wkts": int(r.ww), "bowlBalls": int(r.wb),
            "econ": _r(6 * r.wr / r.wb) if r.wb else None, "bowlAvg": _r(r.wr / r.ww) if r.ww else None,
            "bowlValue": _r(-100 * r.wc / (r.wb + lam_bowl)) if r.wb else None,
            "catches": int(r.ct + r.kc), "stumpings": int(r.st)})
    return out


def bowler_maps(db: pd.DataFrame, inferred: pd.Series | None) -> tuple[pd.Series, pd.Series, pd.Series]:
    """player code -> matchup group, -> pace/spin family, -> batting hand."""
    group = db["bowling_class"].map(GROUPS).dropna()
    fam = db["bowling_family"].replace("", np.nan)
    if inferred is not None:
        fam = fam.fillna(inferred.replace("", np.nan))
    hand = db["batting_hand"].replace("", np.nan).dropna()
    return group, fam.dropna(), hand
