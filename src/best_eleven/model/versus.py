"""Facts about real innings that the XI vs XI projection rests on.

Per (tier, gender, family), over the five most recent seasons in the archive
(internationals between ICC Full Members; every match for leagues), or over
every season when the recent ones hold fewer than MIN_INNINGS usable innings
(a group with fewer than MIN_FALLBACK in all is left out):

  balls    mean legal balls in a first innings that was not shortened
  par      mean runs in those innings
  innings  mean innings per side per match (Tests; 1 in limited-overs cricket)
  share    mean share of an innings' legal balls faced by batting positions 1-11
  quota    most of an innings one bowler may bowl (None in Tests)
  partTime runs saved per ball by occasional bowlers (model/priors.py), attached
           at export; an eleven short of bowlers pays this for the overs it lacks
  n        innings behind balls, par and share

The site turns each player's adjusted runs per ball into runs per innings with
these, so they come from the same archive as the ratings, never from convention.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from .values import FULL_MEMBERS

RECENT_SEASONS = 5
MIN_INNINGS = 30
MIN_FALLBACK = 12
QUOTA = {"fifty": 0.2, "t20": 0.2, "hundred": 0.2, "multi": None}


def _group_key(team_type: str, gender: str, family: str) -> str:
    return f"{'national' if team_type == 'international' else 'league'}:{gender}:{family}"


def versus_constants(warehouse: str | Path) -> dict:
    wh = Path(warehouse)
    m = pd.read_parquet(wh / "matches.parquet",
                        columns=["match_id", "year", "family", "gender", "team_type", "team1", "team2",
                                 "method", "overs", "bpo", "result"])
    inn = pd.read_parquet(wh / "innings.parquet",
                          columns=["match_id", "inning", "batting_team", "super_over", "runs", "legal_balls",
                                   "max_balls", "declared", "forfeited"])
    bat = pd.read_parquet(wh / "batting.parquet", columns=["match_id", "inning", "position", "balls", "super_over"])

    intl = m["team_type"] == "international"
    full = m["team1"].isin(FULL_MEMBERS) & m["team2"].isin(FULL_MEMBERS)
    m = m[~intl | full].copy()
    m["key"] = [_group_key(t, g, f) for t, g, f in zip(m["team_type"], m["gender"], m["family"])]
    inn = inn[(inn["super_over"] == 0) & inn["match_id"].isin(m["match_id"])]
    out = {}
    for key, allg in m.groupby("key"):
        recent = allg[allg["year"] > allg["year"].max() - RECENT_SEASONS]
        row = _constants(key, recent, inn, bat)
        if row is None or row["n"] < MIN_INNINGS:
            row = _constants(key, allg, inn, bat)
        if row is not None and row["n"] >= MIN_FALLBACK:
            out[key] = row
    return out


def _constants(key: str, mg: pd.DataFrame, inn: pd.DataFrame, bat: pd.DataFrame) -> dict | None:
    family = key.split(":")[2]
    ig = inn[inn["match_id"].isin(mg["match_id"])]
    first = ig[(ig["inning"] == 1) & (ig["legal_balls"] > 0) & (ig["forfeited"] == 0)]
    if family != "multi":
        unshortened = mg[(mg["method"].fillna("") == "") & (mg["result"] != "no result")]
        full_balls = (unshortened["overs"] * unshortened["bpo"]).rename("full")
        first = first.merge(unshortened[["match_id"]].assign(full=full_balls.values), on="match_id")
        first = first[(first["max_balls"] < 0) | (first["max_balls"] >= first["full"])]
    if first.empty:
        return None
    b = bat[(bat["super_over"] == 0) & bat["match_id"].isin(first["match_id"]) & (bat["inning"] == 1)]
    b = b[b["position"].between(1, 11)]
    faced = b.pivot_table(index="match_id", columns="position", values="balls", aggfunc="sum", fill_value=0)
    faced = faced.reindex(columns=range(1, 12), fill_value=0)
    legal = first.set_index("match_id")["legal_balls"].reindex(faced.index)
    share = faced.div(legal, axis=0).mean()
    share = share / share.sum()
    if family == "multi":
        played = ig[(ig["forfeited"] == 0) & (ig["legal_balls"] > 0)]
        innings = float(played.groupby("match_id").size().mean() / 2)
    else:
        innings = 1.0
    return {
        "balls": round(float(first["legal_balls"].mean()), 1),
        "par": round(float(first["runs"].mean()), 1),
        "innings": round(innings, 3),
        "share": [round(float(x), 4) for x in share.values],
        "quota": QUOTA.get(family),
        "n": int(len(first)),
        "years": [int(mg["year"].min()), int(mg["year"].max())],
    }


FORMAT_UNIT = {"multi": "test", "fifty": "odi", "t20": "t20i"}


def attach_part_time(groups: dict, part_time: dict) -> dict:
    """Add each group's part-time bowling rate, from its rating unit (men-odi, men-club, ...)."""
    for key, row in groups.items():
        tier, gender, family = key.split(":")
        sex = "men" if gender == "male" else "women"
        unit = f"{sex}-club" if tier == "league" else f"{sex}-{FORMAT_UNIT.get(family, family)}"
        row["partTime"] = part_time.get(unit)
    return groups
