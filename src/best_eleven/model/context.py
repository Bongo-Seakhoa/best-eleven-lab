"""Match context Cricsheet does not record directly: home side and wicketkeeper."""
from __future__ import annotations

import numpy as np
import pandas as pd


def home_teams(matches: pd.DataFrame, min_share: float = 0.4, min_matches: int = 3) -> pd.DataFrame:
    """Infer the home side for each (level, competition, place).

    The side that plays most often at a city (venue when city is missing) is its
    home side, provided it appears in at least ``min_share`` of the matches
    there. Designated home grounds abroad (Pakistan in the UAE) therefore count
    as home, and genuinely neutral venues come out neutral.
    """
    m = matches.copy()
    m["place"] = np.where(m["city"].astype(str) != "", m["city"].astype(str), m["venue"].astype(str))
    m["group"] = np.where(m["team_type"] == "international", "international", m["scope"].astype(str))
    long = pd.concat([m[["match_id", "group", "place", "team1"]].rename(columns={"team1": "team"}),
                      m[["match_id", "group", "place", "team2"]].rename(columns={"team2": "team"})])
    total = m.groupby(["group", "place"]).size().rename("total")
    per = long.groupby(["group", "place", "team"]).size().rename("n").reset_index()
    per = per.merge(total, on=["group", "place"])
    per["share"] = per["n"] / per["total"]
    per = per.sort_values(["group", "place", "n"], ascending=[True, True, False]).drop_duplicates(["group", "place"])
    per = per[(per["share"] >= min_share) & (per["n"] >= min_matches)]
    home = m[["match_id", "group", "place"]].merge(per[["group", "place", "team"]], on=["group", "place"], how="left")
    return home[["match_id", "team"]].rename(columns={"team": "home_team"})


def keepers(wickets: pd.DataFrame, appearances: pd.DataFrame, innings: pd.DataFrame,
            wiki_keepers: set[int] | None = None) -> pd.DataFrame:
    """Infer who kept wicket for each (match, fielding team).

    1. A player credited with a stumping in the match kept wicket.
    2. Otherwise the XI member with the strongest keeping record: a Wikipedia
       wicket-keeper role, or a career stumping rate of at least one per 25
       matches with three or more stumpings.
    Returns match_id, team, keeper, method ('stumping' | 'record').
    """
    wiki_keepers = wiki_keepers or set()
    inn = innings[["match_id", "inning", "bowling_team"]].astype({"bowling_team": str})
    st = wickets[(wickets["kind"] == 6) & (wickets["fielder1"] >= 0) & (wickets["fielder1_sub"] == 0)]
    st = st.merge(inn, on=["match_id", "inning"])
    by_match = (st.groupby(["match_id", "bowling_team", "fielder1"]).size().rename("n").reset_index()
                .sort_values("n", ascending=False).drop_duplicates(["match_id", "bowling_team"]))
    by_match = by_match.rename(columns={"bowling_team": "team", "fielder1": "keeper"})
    by_match["method"] = "stumping"

    career_st = st.groupby("fielder1").size()
    games = appearances.groupby("player").size()
    rate = (career_st.reindex(games.index, fill_value=0) / games).rename("rate")
    score = pd.DataFrame({"rate": rate, "st": career_st.reindex(games.index, fill_value=0)})
    score["wiki"] = score.index.isin(wiki_keepers)
    score["eligible"] = score["wiki"] | ((score["st"] >= 3) & (score["rate"] >= 0.04))
    score["prior"] = score["wiki"].astype(float) + score["rate"]
    app = appearances[["match_id", "team", "player"]].astype({"team": str}).merge(
        score[["prior", "eligible"]], left_on="player", right_index=True, how="left")
    app = app[app["eligible"].fillna(False).astype(bool)]
    best = (app.sort_values("prior", ascending=False).drop_duplicates(["match_id", "team"])
            .rename(columns={"player": "keeper"})[["match_id", "team", "keeper"]])
    best["method"] = "record"
    known = by_match.set_index(["match_id", "team"]).index
    best = best[~best.set_index(["match_id", "team"]).index.isin(known)]
    out = pd.concat([by_match[["match_id", "team", "keeper", "method"]], best], ignore_index=True)
    out["team"] = out["team"].astype(str)
    return out
