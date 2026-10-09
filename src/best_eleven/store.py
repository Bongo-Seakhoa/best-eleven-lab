"""Transactional, local storage with stable source/player identities."""
from __future__ import annotations
import sqlite3
from pathlib import Path

SCHEMA_VERSION = 1
SCHEMA = """
CREATE TABLE IF NOT EXISTS players (id TEXT PRIMARY KEY, name TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS matches (
 id TEXT PRIMARY KEY, start_date TEXT NOT NULL, end_date TEXT NOT NULL,
 format TEXT NOT NULL, gender TEXT NOT NULL, level TEXT NOT NULL,
 competition TEXT NOT NULL, season TEXT NOT NULL, team1 TEXT NOT NULL,
 team2 TEXT NOT NULL, venue TEXT NOT NULL, balls_per_over INTEGER NOT NULL,
 missing_json TEXT NOT NULL, revision INTEGER NOT NULL, data_version TEXT NOT NULL,
 sha256 TEXT NOT NULL, provenance TEXT NOT NULL, is_synthetic INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS match_sources (
 match_id TEXT REFERENCES matches(id) ON DELETE CASCADE, source_key TEXT NOT NULL,
 PRIMARY KEY(match_id,source_key)
);
CREATE TABLE IF NOT EXISTS appearances (
 match_id TEXT REFERENCES matches(id) ON DELETE CASCADE,
 player_id TEXT REFERENCES players(id), team TEXT NOT NULL,
 PRIMARY KEY(match_id,player_id)
);
CREATE TABLE IF NOT EXISTS innings (
 match_id TEXT REFERENCES matches(id) ON DELETE CASCADE, number INTEGER NOT NULL,
 batting_team TEXT NOT NULL, bowling_team TEXT NOT NULL, super_over INTEGER NOT NULL,
 declared INTEGER NOT NULL, forfeited INTEGER NOT NULL, target_runs INTEGER,
 penalty_pre INTEGER NOT NULL, penalty_post INTEGER NOT NULL,
 PRIMARY KEY(match_id,number)
);
CREATE TABLE IF NOT EXISTS deliveries (
 match_id TEXT REFERENCES matches(id) ON DELETE CASCADE, innings INTEGER NOT NULL,
 ordinal INTEGER NOT NULL, over_number INTEGER NOT NULL, actual_delivery TEXT,
 batter TEXT REFERENCES players(id), non_striker TEXT REFERENCES players(id),
 bowler TEXT REFERENCES players(id), bat_runs INTEGER NOT NULL,
 extras INTEGER NOT NULL, total_runs INTEGER NOT NULL, wides INTEGER NOT NULL,
 noballs INTEGER NOT NULL, byes INTEGER NOT NULL, legbyes INTEGER NOT NULL,
 penalty INTEGER NOT NULL, legal_ball INTEGER NOT NULL, faced_ball INTEGER NOT NULL,
 conceded INTEGER NOT NULL, boundary4 INTEGER NOT NULL, boundary6 INTEGER NOT NULL,
 bowler_wickets INTEGER NOT NULL, striker_wickets INTEGER NOT NULL,
 phase TEXT NOT NULL, score_before INTEGER NOT NULL, wickets_before INTEGER NOT NULL,
 PRIMARY KEY(match_id,innings,ordinal),
 FOREIGN KEY(match_id,innings) REFERENCES innings(match_id,number) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS wickets (
 match_id TEXT NOT NULL, innings INTEGER NOT NULL, ordinal INTEGER NOT NULL,
 wicket_number INTEGER NOT NULL, player_out TEXT REFERENCES players(id),
 kind TEXT NOT NULL, bowler_credit INTEGER NOT NULL, is_out INTEGER NOT NULL,
 fielders_json TEXT NOT NULL,
 PRIMARY KEY(match_id,innings,ordinal,wicket_number),
 FOREIGN KEY(match_id,innings,ordinal) REFERENCES deliveries(match_id,innings,ordinal) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS batting (
 match_id TEXT NOT NULL, innings INTEGER NOT NULL, player_id TEXT REFERENCES players(id),
 position INTEGER NOT NULL, runs INTEGER NOT NULL, balls INTEGER NOT NULL,
 outs INTEGER NOT NULL, fours INTEGER NOT NULL, sixes INTEGER NOT NULL,
 PRIMARY KEY(match_id,innings,player_id),
 FOREIGN KEY(match_id,innings) REFERENCES innings(match_id,number) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS fielding (
 match_id TEXT NOT NULL, innings INTEGER NOT NULL, ordinal INTEGER NOT NULL,
 wicket_number INTEGER NOT NULL, player_id TEXT REFERENCES players(id), kind TEXT NOT NULL,
 PRIMARY KEY(match_id,innings,ordinal,wicket_number,player_id),
 FOREIGN KEY(match_id,innings,ordinal,wicket_number) REFERENCES wickets(match_id,innings,ordinal,wicket_number) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS metadata (
 player_id TEXT REFERENCES players(id), format TEXT NOT NULL, level TEXT NOT NULL, valid_from TEXT NOT NULL, valid_to TEXT,
 role TEXT, batting_hand TEXT, bowling_style TEXT, team TEXT,
 captain_matches INTEGER, vice_captain_matches INTEGER, credit REAL, available INTEGER,
 source_url TEXT NOT NULL, observed_at TEXT NOT NULL,
 PRIMARY KEY(player_id,format,level,valid_from,source_url)
);
CREATE TABLE IF NOT EXISTS fetches (
 source_key TEXT PRIMARY KEY, url TEXT NOT NULL, fetched_at TEXT NOT NULL,
 etag TEXT, last_modified TEXT, sha256 TEXT NOT NULL, archive_path TEXT NOT NULL,
 match_count INTEGER NOT NULL, status TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS ingestion_errors (
 id INTEGER PRIMARY KEY, source_key TEXT NOT NULL, file_name TEXT NOT NULL,
 error TEXT NOT NULL, recorded_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS matches_scope ON matches(format,gender,level,competition,end_date);
CREATE INDEX IF NOT EXISTS appearances_team ON appearances(team,player_id);
CREATE INDEX IF NOT EXISTS delivery_batter ON deliveries(batter,match_id);
CREATE INDEX IF NOT EXISTS delivery_bowler ON deliveries(bowler,match_id);
CREATE INDEX IF NOT EXISTS batting_player ON batting(player_id,match_id);
"""


def connect(path: str | Path) -> sqlite3.Connection:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(str(path), timeout=30)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    db.execute("PRAGMA journal_mode=WAL")
    version = db.execute("PRAGMA user_version").fetchone()[0]
    if version not in (0, SCHEMA_VERSION):
        db.close()
        raise ValueError(f"Unsupported database schema {version}")
    db.executescript(SCHEMA)
    db.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
    db.commit()
    return db


def rows(db, sql: str, args=()) -> list[dict]:
    return [dict(r) for r in db.execute(sql, args)]
