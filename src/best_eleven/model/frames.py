"""Warehouse loaders that join match and innings context onto deliveries."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import pandas as pd

MATCH_COLS = ["match_id", "year", "start_date", "family", "gender", "scope", "format", "event",
              "event_stage", "team1", "team2", "city", "venue", "method", "result", "winner"]


class Warehouse:
    def __init__(self, root: str | Path = "data/warehouse"):
        self.root = Path(root)

    @property
    @lru_cache(maxsize=1)
    def matches(self) -> pd.DataFrame:
        return pd.read_parquet(self.root / "matches.parquet")

    @property
    @lru_cache(maxsize=1)
    def innings(self) -> pd.DataFrame:
        return pd.read_parquet(self.root / "innings.parquet")

    @property
    @lru_cache(maxsize=1)
    def players(self) -> pd.DataFrame:
        return pd.read_parquet(self.root / "players.parquet")

    def table(self, name: str) -> pd.DataFrame:
        return pd.read_parquet(self.root / f"{name}.parquet")

    def scopes(self) -> list[str]:
        return sorted(p.stem for p in (self.root / "deliveries").glob("*.parquet"))

    def deliveries(self, scope: str, columns: list[str] | None = None, *,
                   with_context: bool = True) -> pd.DataFrame:
        if columns is not None and with_context:
            columns = list(dict.fromkeys(["match_id", "inning", *columns]))
        d = pd.read_parquet(self.root / "deliveries" / f"{scope}.parquet", columns=columns)
        if not with_context:
            return d
        m = self.matches[MATCH_COLS]
        inn = self.innings[["match_id", "inning", "batting_team", "bowling_team", "runs", "wickets",
                            "legal_balls", "max_balls"]].rename(columns={
            "runs": "innings_total", "wickets": "innings_wickets", "legal_balls": "innings_legal"})
        d = d.merge(m, on="match_id", how="left", validate="many_to_one")
        d = d.merge(inn, on=["match_id", "inning"], how="left", validate="many_to_one")
        for c in ("batting_team", "bowling_team", "scope", "family", "gender", "event", "city",
                  "venue", "team1", "team2", "format", "method", "event_stage", "result", "winner"):
            if c in d:
                d[c] = d[c].astype("category")
        return d
