"""Cricsheet JSON ingestion. A match is replaced atomically; raw archives stay local."""
from __future__ import annotations
from collections import defaultdict
from datetime import date, datetime, timezone
from hashlib import sha256
from pathlib import Path, PurePosixPath
import json
import re
import sqlite3
import zipfile

BOWLER_CREDIT = {"bowled", "caught", "caught and bowled", "lbw", "stumped", "hit wicket"}
NOT_OUT = {"retired hurt", "retired not out"}
KNOWN_WICKETS = BOWLER_CREDIT | NOT_OUT | {"run out", "retired out", "obstructing the field", "hit the ball twice", "handled the ball", "timed out"}
MAX_MEMBER_BYTES = 20_000_000
MAX_ARCHIVE_BYTES = 3_000_000_000


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def phase(fmt: str, over: int) -> str:
    if fmt == "Test":
        return "Overs 0–19" if over < 20 else "Overs 20–79" if over < 80 else "Overs 80+"
    early, late = (6, 15) if fmt == "T20" else (10, 40)
    return "Early overs" if over < early else "Middle overs" if over < late else "Late overs"


def integer(x, label: str) -> int:
    if isinstance(x, bool) or not isinstance(x, int) or x < 0:
        raise ValueError(f"Invalid non-negative integer for {label}: {x!r}")
    return x


def ingest_match(db: sqlite3.Connection, match_id: str, raw: bytes,
                 source_key: str, provenance: str, *, synthetic: bool = False) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", match_id):
        raise ValueError("Unsafe match identifier")
    if len(raw) > MAX_MEMBER_BYTES:
        raise ValueError("Match exceeds size limit")
    d = json.loads(raw)
    meta, info = d["meta"], d["info"]
    version = str(meta["data_version"])
    if version not in {"1.0.0", "1.1.0"}:
        raise ValueError(f"Unreviewed Cricsheet schema version {version}")
    if bool(d.get("synthetic_notice")) and not synthetic:
        raise ValueError("Synthetic input cannot enter the real dataset")
    digest = sha256(raw).hexdigest()
    revision = integer(meta.get("revision", 1), "revision")
    prior = db.execute("SELECT sha256,revision,is_synthetic FROM matches WHERE id=?", (match_id,)).fetchone()
    if prior and prior["is_synthetic"] != int(synthetic):
        raise ValueError("Real/synthetic match identity collision")
    if prior and prior["sha256"] == digest:
        with db:
            db.execute("INSERT OR IGNORE INTO match_sources VALUES (?,?)", (match_id, source_key))
        return "unchanged"
    if prior and prior["revision"] > revision:
        return "older_revision_skipped"
    teams = info["teams"]
    if len(teams) != 2 or teams[0] == teams[1]:
        raise ValueError("A match needs two different teams")
    dates = sorted(date.fromisoformat(str(x)).isoformat() for x in info["dates"])
    if not dates:
        raise ValueError("Match dates are required")
    fmt = {"IT20": "T20"}.get(info["match_type"], info["match_type"])
    if fmt not in {"Test", "ODI", "T20"}:
        raise ValueError(f"Unsupported format: {fmt}")
    gender, level = info["gender"], info["team_type"]
    if gender not in {"male", "female"} or level not in {"international", "club"}:
        raise ValueError("Unreviewed gender or team type")
    registry = info["registry"]["people"]
    comp = "International" if level == "international" else str(info.get("event", {}).get("name", source_key))
    bpo = integer(info["balls_per_over"], "balls_per_over")
    if bpo != 6:
        raise ValueError("This release supports six-ball-over cricket only")
    missing = info.get("missing", [])
    existing_sources = [r[0] for r in db.execute("SELECT source_key FROM match_sources WHERE match_id=?", (match_id,))]
    def pid(name: str) -> str:
        if name not in registry:
            raise ValueError(f"Unresolved player identity: {name}")
        return registry[name]
    with db:
        for name, player_id in registry.items():
            if not re.fullmatch(r"[0-9a-f]{8}", player_id):
                raise ValueError(f"Invalid Cricsheet identity {player_id}")
            db.execute("INSERT INTO players VALUES (?,?) ON CONFLICT(id) DO UPDATE SET name=excluded.name", (player_id, name))
        db.execute("DELETE FROM matches WHERE id=?", (match_id,))
        rec = (match_id, dates[0], dates[-1], fmt, gender, level, comp, str(info["season"]),
               *teams, str(info.get("venue", "Unknown")), bpo, json.dumps(missing), revision, version,
               digest, provenance, int(synthetic))
        db.execute("INSERT INTO matches VALUES (" + ",".join("?" * len(rec)) + ")", rec)
        for sk in set(existing_sources + [source_key]):
            db.execute("INSERT INTO match_sources VALUES (?,?)", (match_id, sk))
        if set(info["players"]) != set(teams):
            raise ValueError("Rosters must describe the two match teams")
        for team, names in info["players"].items():
            for name in names:
                db.execute("INSERT INTO appearances VALUES (?,?,?)", (match_id, pid(name), team))
        for num, inn in enumerate(d.get("innings", []), 1):
            batting_team = inn["team"]
            if batting_team not in teams:
                raise ValueError("Unknown innings team")
            bowling_team = teams[1] if teams[0] == batting_team else teams[0]
            penalties = inn.get("penalty_runs", {})
            pre, post = integer(penalties.get("pre", 0), "pre penalty"), integer(penalties.get("post", 0), "post penalty")
            db.execute("INSERT INTO innings VALUES (?,?,?,?,?,?,?,?,?,?)", (
                match_id, num, batting_team, bowling_team, int(bool(inn.get("super_over", False))),
                int(bool(inn.get("declared", False))), int(bool(inn.get("forfeited", False))),
                inn.get("target", {}).get("runs"), pre, post))
            batting, order, dismissed = {}, [], set()
            total, fallen, ordinal = pre, 0, 0
            ds, ws, fs, seen_overs = [], [], [], set()
            def enter(name):
                if name not in info["players"][batting_team]:
                    raise ValueError("Batter is outside the innings roster")
                p = pid(name)
                if p not in batting:
                    order.append(p)
                    batting[p] = dict(position=len(order), runs=0, balls=0, outs=0, fours=0, sixes=0)
                return p
            for over in inn.get("overs", []):
                on = integer(over["over"], "over")
                if on in seen_overs:
                    raise ValueError("Duplicate over number")
                seen_overs.add(on)
                for ball in over["deliveries"]:
                    ordinal += 1
                    batter, non_striker = enter(ball["batter"]), enter(ball["non_striker"])
                    bowler = pid(ball["bowler"])
                    if ball["bowler"] not in info["players"][bowling_team] or batter == non_striker:
                        raise ValueError("Invalid delivery participants")
                    rr, ex = ball["runs"], ball.get("extras", {})
                    bat_runs, extras, runs = (integer(rr[k], k) for k in ("batter", "extras", "total"))
                    if bat_runs + extras != runs:
                        raise ValueError("Delivery runs do not reconcile")
                    if set(ex) - {"wides", "noballs", "byes", "legbyes", "penalty"}:
                        raise ValueError("Unknown extra type")
                    wides, noballs, byes, legbyes, penalty = [integer(ex.get(k, 0), k) for k in ("wides", "noballs", "byes", "legbyes", "penalty")]
                    if wides and noballs:
                        raise ValueError("A delivery cannot be both wide and no-ball")
                    if sum((wides, noballs, byes, legbyes, penalty)) != extras:
                        raise ValueError("Extra components do not reconcile")
                    legal, faced = int(not (wides or noballs)), int(not wides)
                    conceded = bat_runs + wides + noballs
                    f4, f6 = int(bat_runs == 4 and not rr.get("non_boundary", False)), int(bat_runs == 6 and not rr.get("non_boundary", False))
                    bw = sw = out_count = 0
                    for wn, w in enumerate(ball.get("wickets", []), 1):
                        kind = w["kind"]
                        if kind not in KNOWN_WICKETS:
                            raise ValueError(f"Unknown dismissal kind: {kind}")
                        out_id = enter(w["player_out"])
                        is_out, credit = int(kind not in NOT_OUT), int(kind in BOWLER_CREDIT)
                        if is_out and out_id in dismissed:
                            raise ValueError("Player dismissed twice in one innings")
                        if is_out:
                            dismissed.add(out_id)
                        batting[out_id]["outs"] += is_out
                        fielder_ids = [pid(f if isinstance(f, str) else f["name"]) for f in w.get("fielders", [])]
                        if kind == "caught and bowled" and bowler not in fielder_ids:
                            fielder_ids.append(bowler)
                        ws.append((match_id, num, ordinal, wn, out_id, kind, credit, is_out, json.dumps(fielder_ids)))
                        fs.extend((match_id, num, ordinal, wn, p, kind) for p in dict.fromkeys(fielder_ids))
                        bw += credit
                        sw += int(credit and out_id == batter)
                        out_count += is_out
                    ds.append((match_id, num, ordinal, on, str(ball.get("actual_delivery", "")),
                               batter, non_striker, bowler, bat_runs, extras, runs, wides, noballs, byes, legbyes,
                               penalty, legal, faced, conceded, f4, f6, bw, sw, phase(fmt, on), total, fallen))
                    for k, v in (("runs", bat_runs), ("balls", faced), ("fours", f4), ("sixes", f6)):
                        batting[batter][k] += v
                    total += runs
                    fallen += out_count
            if ds:
                db.executemany("INSERT INTO deliveries VALUES (" + ",".join("?" * 26) + ")", ds)
            if ws:
                db.executemany("INSERT INTO wickets VALUES (?,?,?,?,?,?,?,?,?)", ws)
            if fs:
                db.executemany("INSERT INTO fielding VALUES (?,?,?,?,?,?)", fs)
            for p, b in batting.items():
                db.execute("INSERT INTO batting VALUES (?,?,?,?,?,?,?,?,?)", (
                    match_id, num, p, b["position"], b["runs"], b["balls"], b["outs"], b["fours"], b["sixes"]))
    return "updated" if prior else "inserted"


def ingest_archive(db, archive: str | Path, source_key: str, provenance: str, *, synthetic=False) -> dict:
    counts, errors = defaultdict(int), []
    with zipfile.ZipFile(archive) as z:
        members = z.infolist()
        if sum(m.file_size for m in members) > MAX_ARCHIVE_BYTES:
            raise ValueError("Expanded archive exceeds safety limit")
        members = [m for m in members if m.filename.endswith(".json") and not m.is_dir()]
        if not members:
            raise ValueError("Archive contains no match JSON files")
        seen = set()
        for m in members:
            path = PurePosixPath(m.filename)
            if path.is_absolute() or ".." in path.parts or "\\" in m.filename or m.file_size > MAX_MEMBER_BYTES:
                raise ValueError("Unsafe or oversized archive member")
            if path.stem in seen:
                raise ValueError("Duplicate match identity in archive")
            seen.add(path.stem)
        for m in members:
            try:
                status = ingest_match(db, PurePosixPath(m.filename).stem, z.read(m), source_key, provenance, synthetic=synthetic)
                counts[status] += 1
            except (ValueError, KeyError, TypeError, sqlite3.Error, zipfile.BadZipFile) as exc:
                counts["failed"] += 1
                errors.append({"file": m.filename, "error": str(exc)})
                with db:
                    db.execute("INSERT INTO ingestion_errors(source_key,file_name,error,recorded_at) VALUES (?,?,?,?)", (source_key, m.filename, str(exc), utcnow()))
    return {"source": source_key, "counts": dict(counts), "errors": errors, "status": "partial" if errors else "ok"}
