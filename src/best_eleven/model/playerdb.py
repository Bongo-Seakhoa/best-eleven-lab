"""Player database: one row per Cricsheet person with attributes, national
team, and per-scope availability and leadership flags.

Match data alone cannot say who has retired, who is in a current squad, or who
captains. Those come from the reference snapshots in data/reference (see
enrich/), each carrying its source page and revision. Missing snapshots leave
the corresponding fields empty rather than guessed.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from .frames import Warehouse
from .values import FULL_MEMBERS

INTL_SCOPES = {"men-test": ("male", "Test"), "men-odi": ("male", "ODI"), "men-t20i": ("male", "T20I"),
               "women-test": ("female", "Test"), "women-odi": ("female", "ODI"),
               "women-t20i": ("female", "T20I")}
ACTIVE_MONTHS = {"Test": 24, "ODI": 18, "T20I": 18, "league": 24}
PACE = {"RF", "RFM", "RMF", "RM", "LF", "LFM", "LMF", "LM"}
SPIN = {"OB", "LB", "SLA", "LWS"}


def _read(path: Path) -> pd.DataFrame | None:
    return pd.read_csv(path, dtype=str, keep_default_na=False) if path.exists() else None


def national_teams(wh: Warehouse) -> pd.DataFrame:
    """Most-played international side per player (ties: most recent)."""
    m = wh.matches[wh.matches["team_type"] == "international"][["match_id", "start_date"]]
    ap = wh.table("appearances").merge(m, on="match_id")
    ap["team"] = ap["team"].astype(str)
    g = ap.groupby(["player", "team"]).agg(n=("match_id", "size"), last=("start_date", "max")).reset_index()
    g = g.sort_values(["player", "n", "last"], ascending=[True, False, False]).drop_duplicates("player")
    return g.set_index("player")[["team"]].rename(columns={"team": "national_team"})


def build_player_db(warehouse: str | Path, reference: str | Path, competitions: str | Path) -> dict:
    wh = Warehouse(warehouse)
    ref = Path(reference)
    P = wh.players.set_index("player")
    db = P[["id", "name", "first_date", "last_date"]].copy()
    db = db.join(national_teams(wh))

    wiki = _read(ref / "players_wiki.csv")
    if wiki is not None and len(wiki):
        w = wiki[wiki["cricsheet_id"] != ""].drop_duplicates("cricsheet_id").set_index("cricsheet_id")
        cols = ["wikipedia_title", "full_name", "birth_date", "country", "batting_hand", "bowling_class",
                "bowling_family", "bowling_arm", "role", "active_international", "retired_test",
                "retired_odi", "retired_t20i", "retired_international", "career_json"]
        cols = [c for c in cols if c in w.columns]
        db = db.join(w[cols], on="id")
    for c in ("wikipedia_title", "full_name", "birth_date", "country", "batting_hand", "bowling_class",
              "bowling_family", "bowling_arm", "role", "active_international", "retired_test",
              "retired_odi", "retired_t20i", "retired_international", "career_json"):
        if c not in db:
            db[c] = ""
        db[c] = db[c].fillna("")
    db["fam_src"] = np.where(db["bowling_family"] != "", "wikipedia", "")
    db["wk"] = db["role"].str.contains("wicket-keeper", na=False).astype(int)

    squads = _read(ref / "squads.csv")
    captains = _read(ref / "captain_totals.csv")
    data_end = pd.Timestamp(wh.matches["end_date"].max())
    leagues = json.loads(Path(competitions).read_text(encoding="utf-8"))["leagues"]
    return {"db": db, "squads": squads, "captains": captains, "data_end": data_end,
            "leagues": {lg["key"]: lg for lg in leagues}, "wh": wh}


STALE_MONTHS = 15


def current_squads(squads: pd.DataFrame, data_end: pd.Timestamp) -> pd.DataFrame:
    """Drop squad sections whose own 'as of' date is too old to count as current,
    and players the page marks as withdrawn."""
    as_of = pd.to_datetime(squads.get("as_of", pd.Series("", index=squads.index)), errors="coerce")
    fresh = as_of.isna() | (as_of >= data_end - pd.DateOffset(months=STALE_MONTHS))
    status = squads.get("status", pd.Series("", index=squads.index))
    return squads[fresh & (status != "withdrawn")]


def marked(s: pd.DataFrame, formats_col: str, marker: str, fmt: str) -> pd.Series:
    """Captain/vice-captain for a format: an explicit per-format mark, or a bare
    C/VC marker on a table that lists no formats for it."""
    explicit = s[formats_col].str.contains(fmt, na=False)
    bare = (s.get("captain", "") == marker) & (s["captain_formats"] == "") & (s["vice_captain_formats"] == "")
    return explicit | bare


def last_dates(wh: Warehouse, scope: str) -> pd.Series:
    m = wh.matches[wh.matches["scope"] == scope][["match_id", "end_date"]]
    ap = wh.table("appearances").merge(m, on="match_id")
    return ap.groupby("player")["end_date"].max()


def scope_flags(ctx: dict, scope: str, players: pd.Index, seasons: pd.DataFrame) -> pd.DataFrame:
    """Per-player flags for one scope: squad, active, retired, capt, vc, pre, overseas."""
    db, wh = ctx["db"], ctx["wh"]
    out = pd.DataFrame(index=players)
    last = last_dates(wh, scope).reindex(players)
    out["last"] = last.fillna("")
    squads, caps = ctx["squads"], ctx["captains"]
    ids = db.loc[players, "id"]
    out["squad"] = 0; out["vc"] = 0; out["cc"] = 0; out["capt"] = 0; out["retired"] = 0; out["pre"] = 0
    out["overseas"] = 0
    if scope in INTL_SCOPES:
        gender, fmt = INTL_SCOPES[scope]
        months = ACTIVE_MONTHS[fmt]
        nat = db.loc[players, "national_team"].fillna("")
        if squads is not None:
            s = current_squads(squads, ctx["data_end"])
            s = s[(s["level"] == "international") & (s["gender"] == gender) & (s["cricsheet_id"] != "")]
            s = s[s["forms"].str.contains(fmt, na=False)]
            out["squad"] = ids.isin(set(s["cricsheet_id"])).astype(int).to_numpy()
            out["vc"] = ids.isin(set(s.loc[marked(s, "vice_captain_formats", "VC", fmt), "cricsheet_id"])).astype(int).to_numpy()
            out["cc"] = ids.isin(set(s.loc[marked(s, "captain_formats", "C", fmt), "cricsheet_id"])).astype(int).to_numpy()
        if caps is not None:
            c = caps[(caps["level"] == "international") & (caps["gender"] == gender) & (caps["format"] == fmt)
                     & (caps["cricsheet_id"] != "")]
            cm = c.groupby("cricsheet_id")["played"].apply(lambda x: pd.to_numeric(x, errors="coerce").fillna(0).sum())
            out["capt"] = ids.map(cm).fillna(0).astype(int).to_numpy()
        key = {"Test": "retired_test", "ODI": "retired_odi", "T20I": "retired_t20i"}[fmt]
        r = (db.loc[players, key] == "1") | (db.loc[players, "retired_international"] == "1")
        out["retired"] = r.astype(int).to_numpy()
        # Caps before ball-by-ball coverage began, from the Wikipedia career totals.
        first_year = seasons.groupby("player")["year"].min().reindex(players)
        start = int(seasons["year"].min())
        cs_matches = seasons.groupby("player")["m"].sum().reindex(players).fillna(0)
        wiki_key = {"Test": ("Test", "WTest"), "ODI": ("ODI", "WODI"), "T20I": ("T20I", "WT20I")}[fmt]
        pre = []
        for pi, cj in zip(players, db.loc[players, "career_json"]):
            n = 0
            if cj and first_year.get(pi, 9999) <= start + 1:
                try:
                    career = json.loads(cj)
                    for k in wiki_key:
                        if k in career and career[k].get("matches"):
                            n = max(n, int(career[k]["matches"]) - int(cs_matches.get(pi, 0)))
                except (ValueError, TypeError):
                    n = 0
            pre.append(max(0, n))
        out["pre"] = pre
    else:
        months = ACTIVE_MONTHS["league"]
        lg = ctx["leagues"].get(scope, {})
        if squads is not None and lg:
            s = current_squads(squads, ctx["data_end"])
            s = s[(s["level"] == "franchise") & (s["competition"] == lg["label"]) & (s["cricsheet_id"] != "")]
            out["squad"] = ids.isin(set(s["cricsheet_id"])).astype(int).to_numpy()
            cur = s[s["captain_formats"] != ""] if "captain_formats" in s else s.iloc[0:0]
            out["cc"] = ids.isin(set(cur["cricsheet_id"])).astype(int).to_numpy()
        if caps is not None and lg:
            c = caps[(caps["level"] == "franchise") & (caps["competition"] == lg["label"]) & (caps["cricsheet_id"] != "")]
            cm = c.groupby("cricsheet_id")["played"].apply(lambda x: pd.to_numeric(x, errors="coerce").fillna(0).sum())
            out["capt"] = ids.map(cm).fillna(0).astype(int).to_numpy()
        host = lg.get("host", "")
        nat = db.loc[players, "national_team"].fillna("")
        country = db.loc[players, "country"].fillna("")
        team = np.where(nat != "", nat, country)
        out["overseas"] = ((team != "") & (team != host)).astype(int)
        out["retired"] = 0
    cutoff = (ctx["data_end"] - pd.DateOffset(months=months)).strftime("%Y-%m-%d")
    recent = out["last"].astype(str) >= cutoff
    # A current squad place overrides a reported retirement (players do come back).
    out["active"] = ((out["squad"] == 1) | (recent & (out["retired"] == 0))).astype(int)
    return out
