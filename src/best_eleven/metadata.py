"""Dated, source-attributed roles and player attributes. Blank is unknown, not zero."""
from __future__ import annotations
import csv
import math
from datetime import date
from pathlib import Path
from urllib.parse import urlparse
FIELDS = ["player_id", "format", "level", "valid_from", "valid_to", "role", "batting_hand", "bowling_style", "team", "captain_matches", "vice_captain_matches", "credit", "available", "source_url", "observed_at"]
ROLES = {"opener", "bat", "keeper", "all_rounder", "bowler"}


def import_metadata(db, path: str | Path) -> dict:
    values = []
    with Path(path).open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames or set(reader.fieldnames) != set(FIELDS) or len(reader.fieldnames) != len(FIELDS):
            raise ValueError("Metadata CSV needs exactly these columns: " + ",".join(FIELDS))
        for line, r in enumerate(reader, 2):
            if None in r or any(v is None for v in r.values()):
                raise ValueError(f"Line {line}: CSV row does not match its header")
            if not db.execute("SELECT 1 FROM players WHERE id=?", (r["player_id"],)).fetchone():
                raise ValueError(f"Line {line}: unknown player ID; ingest matches first")
            if r["format"] not in {"Test", "ODI", "T20"} or r["level"] not in {"international", "club"}:
                raise ValueError("Metadata must declare a format and team level")
            parsed = urlparse(r["source_url"])
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                raise ValueError("A source URL is required")
            for col in ("valid_from", "observed_at"):
                date.fromisoformat(r[col])
            if r["valid_to"]:
                date.fromisoformat(r["valid_to"])
                if r["valid_to"] < r["valid_from"]:
                    raise ValueError("valid_to precedes valid_from")
            if r["role"] and r["role"] not in ROLES:
                raise ValueError("Unrecognised role")
            if r["batting_hand"] and r["batting_hand"] not in {"right", "left"}:
                raise ValueError("Batting hand must be right, left or blank")
            for col in ("captain_matches", "vice_captain_matches", "available"):
                if r[col]:
                    r[col] = int(r[col])
                    if r[col] < 0 or (col == "available" and r[col] not in (0, 1)):
                        raise ValueError(f"Invalid {col}")
            if r["credit"]:
                r["credit"] = float(r["credit"])
                if not math.isfinite(r["credit"]) or r["credit"] < 0:
                    raise ValueError("Invalid credit")
            values.append(tuple(r[k] if r[k] != "" else None for k in FIELDS))
    with db:
        db.executemany("INSERT OR REPLACE INTO metadata VALUES (" + ",".join("?" * len(FIELDS)) + ")", values)
    return {"imported": len(values), "meaning": "Source-attributed appointments and roles, not measured leadership effectiveness"}
