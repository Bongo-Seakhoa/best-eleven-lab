"""Cricsheet JSON archive -> columnar warehouse (Parquet).

One streaming pass over the archive. Each match is validated as a unit: a match
that breaks an accounting rule is quarantined with its reason rather than being
partially stored. Deliveries are partitioned by scope so analysis can load one
national format or league at a time on a small machine.
"""
from __future__ import annotations

import hashlib
import json
import time
from array import array
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from pathlib import Path, PurePosixPath
import re
import zipfile

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

try:  # orjson is ~3x faster on the 4 GB archive; json is the portable fallback
    import orjson
    _loads = orjson.loads
except ImportError:  # pragma: no cover
    _loads = json.loads

SUPPORTED_VERSIONS = {"1.0.0", "1.1.0", "1.2.0", "1.3.0"}
WICKET_KINDS = ["", "caught", "bowled", "lbw", "run out", "caught and bowled", "stumped",
                "hit wicket", "retired hurt", "retired out", "retired not out",
                "obstructing the field", "handled the ball", "timed out", "hit the ball twice"]
KIND = {k: i for i, k in enumerate(WICKET_KINDS)}
BOWLER_CREDIT = {"bowled", "caught", "caught and bowled", "lbw", "stumped", "hit wicket"}
NOT_OUT = {"retired hurt", "retired not out"}
EXTRA_KEYS = {"wides", "noballs", "byes", "legbyes", "penalty"}
MAX_MEMBER_BYTES = 25_000_000
MAX_ARCHIVE_BYTES = 12_000_000_000

# Phase boundaries in legal balls already bowled (limited overs) or overs (multi-day).
PHASE_EDGES = {"fifty": (60, 240), "t20": (36, 90), "hundred": (25, 75), "multi": (20, 80)}
DEFAULT_BALLS = {"fifty": 300, "t20": 120, "hundred": 100}
INTL_FORMAT = {"Test": "test", "ODI": "odi", "T20": "t20i"}

DELIVERY_SPEC = [
    ("match_id", "i"), ("inning", "b"), ("ordinal", "h"), ("over", "h"), ("legal_before", "h"),
    ("batter", "i"), ("non_striker", "i"), ("bowler", "i"),
    ("runs_batter", "b"), ("runs_extras", "b"), ("runs_total", "b"),
    ("wides", "b"), ("noballs", "b"), ("byes", "b"), ("legbyes", "b"), ("penalty", "b"),
    ("four", "b"), ("six", "b"), ("legal", "b"), ("faced", "b"), ("conceded", "b"),
    ("score_before", "h"), ("wkts_before", "b"),
    ("striker_out", "b"), ("striker_kind", "b"), ("bowler_wkt", "b"),
    ("ns_out", "b"), ("ns_kind", "b"), ("fielder", "i"), ("fielder_sub", "b"),
    ("batter_pos", "b"), ("ns_pos", "b"), ("phase", "b"), ("balls_rem", "h"),
    ("target", "h"), ("super_over", "b"),
]
WICKET_SPEC = [
    ("match_id", "i"), ("inning", "b"), ("ordinal", "h"), ("player_out", "i"), ("kind", "b"),
    ("is_out", "b"), ("bowler_credit", "b"), ("bowler", "i"), ("striker", "i"),
    ("fielder1", "i"), ("fielder1_sub", "b"), ("fielder2", "i"), ("fielder2_sub", "b"),
    ("n_fielders", "b"), ("super_over", "b"),
]
BATTING_SPEC = [
    ("match_id", "i"), ("inning", "b"), ("team", "s"), ("player", "i"), ("position", "b"),
    ("runs", "h"), ("balls", "h"), ("fours", "h"), ("sixes", "h"), ("dots", "h"),
    ("out", "b"), ("kind", "b"), ("bowler", "i"), ("fielder", "i"), ("super_over", "b"),
]
BOWLING_SPEC = [
    ("match_id", "i"), ("inning", "b"), ("team", "s"), ("player", "i"), ("balls", "h"),
    ("conceded", "h"), ("wickets", "b"), ("wides", "h"), ("noballs", "h"), ("dots", "h"),
    ("fours", "h"), ("sixes", "h"), ("maidens", "b"), ("overs", "h"), ("super_over", "b"),
]
APPEARANCE_SPEC = [("match_id", "i"), ("team", "s"), ("player", "i"), ("replacement", "b"),
                   ("supersub", "b")]
INNINGS_SPEC = [
    ("match_id", "i"), ("inning", "b"), ("batting_team", "s"), ("bowling_team", "s"),
    ("super_over", "b"), ("declared", "b"), ("forfeited", "b"), ("target_runs", "h"),
    ("target_balls", "h"), ("runs", "h"), ("wickets", "b"), ("legal_balls", "h"),
    ("max_balls", "h"), ("penalty_pre", "h"), ("penalty_post", "h"), ("absent_hurt", "b"),
]
NUMPY = {"b": np.int8, "h": np.int16, "i": np.int32, "d": np.float64}


class Buffer:
    """Typed column buffers; rows are added per match in one transposed extend."""

    def __init__(self, spec):
        self.spec = spec
        self.cols = [[] if t == "s" else array(t) for _, t in spec]

    def extend(self, rows):
        if rows:
            for col, values in zip(self.cols, zip(*rows)):
                col.extend(values)

    def __len__(self):
        return len(self.cols[0])

    def table(self) -> pa.Table:
        arrays = []
        for (name, t), col in zip(self.spec, self.cols):
            if t == "s":
                arrays.append(pa.array(col, type=pa.string()).dictionary_encode())
            else:
                arrays.append(pa.array(np.frombuffer(col, dtype=NUMPY[t]) if len(col) else
                                       np.zeros(0, dtype=NUMPY[t])))
        return pa.table(arrays, names=[n for n, _ in self.spec])

    def clear(self):
        self.cols = [[] if t == "s" else array(t) for _, t in self.spec]


class Players:
    """Stable integer codes for Cricsheet's eight-hex person identifiers."""

    def __init__(self):
        self.code: dict[str, int] = {}
        self.ids: list[str] = []
        self.name: list[str] = []
        self.name_date: list[str] = []
        self.first: list[str] = []
        self.last: list[str] = []

    def get(self, pid: str, name: str, day: str) -> int:
        c = self.code.get(pid)
        if c is None:
            c = self.code[pid] = len(self.ids)
            self.ids.append(pid); self.name.append(name); self.name_date.append(day)
            self.first.append(day); self.last.append(day)
            return c
        if day >= self.name_date[c]:
            self.name[c], self.name_date[c] = name, day
        if day < self.first[c]:
            self.first[c] = day
        if day > self.last[c]:
            self.last[c] = day
        return c

    def table(self) -> pa.Table:
        return pa.table({"player": np.arange(len(self.ids), dtype=np.int32), "id": self.ids,
                         "name": self.name, "first_date": self.first, "last_date": self.last})


def load_competitions(path: str | Path) -> dict[tuple[str, str], dict]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    out = {}
    for lg in data["leagues"]:
        for ev in lg["events"]:
            out[(ev, lg["gender"])] = lg
    return out


def family_of(match_type: str, bpo: int) -> str:
    if bpo == 5:
        return "hundred"
    return {"Test": "multi", "MDM": "multi", "ODI": "fifty", "ODM": "fifty"}.get(match_type, "t20")


def scope_of(info: dict, leagues: dict) -> tuple[str, str]:
    """Return (scope key, display format)."""
    g, mt = info["gender"], info["match_type"]
    if info["team_type"] == "international":
        f = INTL_FORMAT.get(mt)
        if f:
            return f"{'men' if g == 'male' else 'women'}-{f}", {"t20i": "T20I"}.get(f, mt)
        return "other", mt
    lg = leagues.get((info.get("event", {}).get("name"), g))
    if lg:
        return lg["key"], "Hundred" if info.get("balls_per_over") == 5 else "T20"
    return "other", mt


def balls_from_overs(overs, bpo: int) -> int:
    whole = int(overs)
    part = round((float(overs) - whole) * 10)
    return whole * bpo + part


def phase_of(fam: str, over: int, legal_before: int) -> int:
    lo, hi = PHASE_EDGES[fam]
    x = over if fam == "multi" else legal_before
    return 0 if x < lo else 1 if x < hi else 2


def nonneg(x, label: str) -> int:
    if isinstance(x, bool) or not isinstance(x, int) or x < 0:
        raise ValueError(f"invalid count for {label}: {x!r}")
    return x


class Warehouse:
    def __init__(self, out: Path, leagues: dict, flush_rows: int = 300_000):
        self.out = out
        self.leagues = leagues
        self.flush_rows = flush_rows
        self.players = Players()
        self.deliveries: dict[str, Buffer] = defaultdict(lambda: Buffer(DELIVERY_SPEC))
        self.writers: dict[str, pq.ParquetWriter] = {}
        self.wickets = Buffer(WICKET_SPEC)
        self.batting = Buffer(BATTING_SPEC)
        self.bowling = Buffer(BOWLING_SPEC)
        self.appearances = Buffer(APPEARANCE_SPEC)
        self.innings = Buffer(INNINGS_SPEC)
        self.matches: list[dict] = []
        self.quarantine: list[dict] = []
        self.counts: Counter = Counter()
        (out / "deliveries").mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------ match
    def add_match(self, match_id: int, raw: bytes, source_file: str = "") -> None:
        d = _loads(raw)
        meta, info = d["meta"], d["info"]
        version = str(meta["data_version"])
        if version not in SUPPORTED_VERSIONS:
            raise ValueError(f"unreviewed Cricsheet schema {version}")
        teams = info["teams"]
        if len(teams) != 2 or teams[0] == teams[1]:
            raise ValueError("a match needs two different teams")
        dates = sorted(date.fromisoformat(str(x)).isoformat() for x in info["dates"])
        bpo = nonneg(info["balls_per_over"], "balls_per_over")
        if bpo not in (5, 6):
            raise ValueError(f"unsupported balls per over {bpo}")
        scope, fmt = scope_of(info, self.leagues)
        fam = family_of(info["match_type"], bpo)
        registry = info["registry"]["people"]
        day = dates[-1]
        for pid in registry.values():
            if not re.fullmatch(r"[0-9a-f]{8}", pid):
                raise ValueError(f"invalid person identifier {pid}")
        code = {name: self.players.get(pid, name, day) for name, pid in registry.items()}

        def pc(name: str) -> int:
            try:
                return code[name]
            except KeyError:
                raise ValueError(f"unregistered person {name}") from None

        roster = info["players"]
        if set(roster) != set(teams):
            raise ValueError("rosters do not describe the two teams")
        replaced_in = set()
        sched_overs = info.get("overs")
        rows_app, rows_inn, rows_del, rows_wk, rows_bat, rows_bowl = [], [], [], [], [], []
        supersubs = set((info.get("supersubs") or {}).values())

        innings_list = d.get("innings", [])
        for num, inn in enumerate(innings_list, 1):
            bt = inn["team"]
            if bt not in teams:
                raise ValueError("innings team is not a match team")
            ft = teams[1] if teams[0] == bt else teams[0]
            so = int(bool(inn.get("super_over", False)))
            pen = inn.get("penalty_runs", {})
            pre, post = nonneg(pen.get("pre", 0), "pre penalty"), nonneg(pen.get("post", 0), "post penalty")
            target = inn.get("target") or {}
            t_runs = target.get("runs")
            t_balls = balls_from_overs(target["overs"], bpo) if target.get("overs") is not None else None
            if fam == "multi" or so:
                max_balls = -1
            elif t_balls is not None:
                max_balls = t_balls
            elif sched_overs:
                max_balls = balls_from_overs(sched_overs, bpo)
            else:
                max_balls = DEFAULT_BALLS[fam]
            bat_roster, bowl_roster = set(roster[bt]), set(roster[ft])
            order: dict[int, int] = {}
            bstat: dict[int, list] = {}   # runs, balls, fours, sixes, dots, out, kind, bowler, fielder
            wstat: dict[int, list] = {}   # balls, conceded, wkts, wides, noballs, dots, 4s, 6s, overs-set
            over_track: dict[tuple, list] = {}
            dismissed = set()
            score, fallen, legal_count, ordinal = pre, 0, 0, 0

            def enter(name: str) -> int:
                if name not in bat_roster:
                    raise ValueError(f"batter {name} outside batting roster")
                p = pc(name)
                if p not in order:
                    order[p] = len(order) + 1
                    bstat[p] = [0, 0, 0, 0, 0, 0, 0, -1, -1]
                return p

            seen_overs = set()
            for over in inn.get("overs", []):
                on = nonneg(over["over"], "over")
                if on in seen_overs:
                    raise ValueError("duplicate over number")
                seen_overs.add(on)
                for ball in over["deliveries"]:
                    ordinal += 1
                    striker, ns = enter(ball["batter"]), enter(ball["non_striker"])
                    if striker == ns:
                        raise ValueError("striker and non-striker are the same person")
                    if ball["bowler"] not in bowl_roster:
                        raise ValueError(f"bowler {ball['bowler']} outside fielding roster")
                    bowler = pc(ball["bowler"])
                    rr = ball["runs"]
                    rb, rx, rt = nonneg(rr["batter"], "batter runs"), nonneg(rr["extras"], "extras"), nonneg(rr["total"], "total")
                    if rb + rx != rt:
                        raise ValueError("delivery runs do not reconcile")
                    ex = ball.get("extras") or {}
                    if set(ex) - EXTRA_KEYS:
                        raise ValueError(f"unknown extra {set(ex) - EXTRA_KEYS}")
                    wd, nb, by, lb, pn = (nonneg(ex.get(k, 0), k) for k in ("wides", "noballs", "byes", "legbyes", "penalty"))
                    if wd and nb:
                        raise ValueError("a delivery cannot be both wide and no-ball")
                    if wd + nb + by + lb + pn != rx:
                        raise ValueError("extra components do not reconcile")
                    legal = int(not (wd or nb))
                    faced = int(not wd)
                    conceded = rb + wd + nb
                    nbdry = bool(rr.get("non_boundary", False))
                    f4 = int(rb == 4 and not nbdry)
                    f6 = int(rb == 6 and not nbdry)
                    ph = phase_of(fam, on, legal_count)
                    balls_rem = max_balls - legal_count if max_balls > 0 else -1
                    s_out = s_kind = b_wkt = n_out = n_kind = f_sub = 0
                    fielder = -1
                    outs_here = 0
                    for w in ball.get("wickets", []):
                        kind = w["kind"]
                        if kind not in KIND:
                            raise ValueError(f"unknown dismissal kind {kind}")
                        out_p = enter(w["player_out"])
                        is_out = int(kind not in NOT_OUT)
                        credit = int(kind in BOWLER_CREDIT)
                        if is_out:
                            if out_p in dismissed:
                                raise ValueError("player dismissed twice in one innings")
                            dismissed.add(out_p)
                        fl = []
                        for f in w.get("fielders", []) or []:
                            nm = f if isinstance(f, str) else f.get("name")
                            sub = int(bool(isinstance(f, dict) and f.get("substitute")))
                            if nm is None:  # unnamed substitute fielder
                                fl.append((-1, 1))
                            else:
                                fl.append((pc(nm), sub))
                        if kind == "caught and bowled" and not fl:
                            fl.append((bowler, 0))
                        f1, f1s = fl[0] if fl else (-1, 0)
                        f2, f2s = fl[1] if len(fl) > 1 else (-1, 0)
                        rows_wk.append((match_id, num, ordinal, out_p, KIND[kind], is_out, credit,
                                        bowler, striker, f1, f1s, f2, f2s, len(fl), so))
                        st = bstat[out_p]
                        if is_out:
                            st[5], st[6] = 1, KIND[kind]
                            st[7] = bowler if credit else -1
                            st[8] = f1
                        elif not st[5]:
                            st[6] = KIND[kind]
                        b_wkt += credit
                        outs_here += is_out
                        if out_p == striker:
                            s_out, s_kind, fielder, f_sub = is_out, KIND[kind], f1, f1s
                        else:
                            n_out, n_kind = is_out, KIND[kind]
                    rows_del.append((match_id, num, ordinal, on, legal_count, striker, ns, bowler,
                                     rb, rx, rt, wd, nb, by, lb, pn, f4, f6, legal, faced, conceded,
                                     score, fallen, s_out, s_kind, b_wkt, n_out, n_kind, fielder, f_sub,
                                     order[striker], order[ns], ph, balls_rem,
                                     t_runs if t_runs is not None else -1, so))
                    st = bstat[striker]
                    st[0] += rb; st[1] += faced; st[2] += f4; st[3] += f6
                    st[4] += int(faced and rb == 0)
                    ws = wstat.get(bowler)
                    if ws is None:
                        ws = wstat[bowler] = [0, 0, 0, 0, 0, 0, 0, 0, set()]
                    ws[0] += legal; ws[1] += conceded; ws[2] += b_wkt; ws[3] += wd; ws[4] += nb
                    ws[5] += int(legal and conceded == 0); ws[6] += f4; ws[7] += f6; ws[8].add(on)
                    ot = over_track.get(on)
                    if ot is None:
                        ot = over_track[on] = [set(), 0, 0]
                    ot[0].add(bowler); ot[1] += conceded; ot[2] += legal
                    score += rt
                    fallen += outs_here
                    legal_count += legal
            maidens = Counter()
            for bowlers, conc, leg in over_track.values():
                if len(bowlers) == 1 and conc == 0 and leg == bpo:
                    maidens[next(iter(bowlers))] += 1
            for p, pos in order.items():
                st = bstat[p]
                rows_bat.append((match_id, num, bt, p, pos, st[0], st[1], st[2], st[3], st[4],
                                 st[5], st[6], st[7], st[8], so))
            for p, ws in wstat.items():
                rows_bowl.append((match_id, num, ft, p, ws[0], ws[1], ws[2], ws[3], ws[4], ws[5],
                                  ws[6], ws[7], maidens[p], len(ws[8]), so))
            rows_inn.append((match_id, num, bt, ft, so, int(bool(inn.get("declared"))),
                             int(bool(inn.get("forfeited"))), t_runs if t_runs is not None else -1,
                             t_balls if t_balls is not None else -1, score + post, fallen,
                             legal_count, max_balls, pre, post, len(inn.get("absent_hurt", []) or [])))

        for ov in innings_list:
            for o in ov.get("overs", []):
                for b in o["deliveries"]:
                    for r in (b.get("replacements") or {}).get("match", []) or []:
                        replaced_in.add(r.get("in"))
        for team, names in roster.items():
            for name in names:
                rows_app.append((match_id, team, pc(name), int(name in replaced_in), int(name in supersubs)))

        outcome = info.get("outcome", {})
        by = outcome.get("by", {})
        if "winner" in outcome:
            result = "win"
        else:
            result = outcome.get("result", "unknown")
        event = info.get("event", {}) or {}
        pom = ",".join(registry.get(n, "") for n in info.get("player_of_match", []) or [])
        self.matches.append({
            "match_id": match_id, "source_file": source_file or str(match_id), "data_version": version, "revision": int(meta.get("revision", 1)),
            "created": str(meta.get("created", "")), "start_date": dates[0], "end_date": dates[-1],
            "year": int(dates[0][:4]), "season": str(info.get("season", "")),
            "match_type": info["match_type"], "format": fmt, "family": fam,
            "gender": info["gender"], "team_type": info["team_type"], "scope": scope,
            "event": str(event.get("name", "")), "event_stage": str(event.get("stage", "")),
            "event_group": str(event.get("group", "")),
            "match_number": int(event["match_number"]) if isinstance(event.get("match_number"), int) else -1,
            "team1": teams[0], "team2": teams[1], "venue": str(info.get("venue", "")),
            "city": str(info.get("city", "")),
            "toss_winner": str((info.get("toss") or {}).get("winner", "")),
            "toss_decision": str((info.get("toss") or {}).get("decision", "")),
            "winner": str(outcome.get("winner", "")), "result": result,
            "by_runs": int(by.get("runs", -1)) if "innings" not in by else -1,
            "by_wickets": int(by.get("wickets", -1)),
            "by_innings": int("innings" in by),
            "innings_runs": int(by.get("runs", -1)) if "innings" in by else -1,
            "method": str(outcome.get("method", "")),
            "eliminator": str(outcome.get("eliminator", outcome.get("bowl_out", ""))),
            "overs": float(sched_overs) if sched_overs else -1.0, "bpo": bpo,
            "n_innings": len(innings_list), "player_of_match": pom,
            "match_type_number": int(info.get("match_type_number", -1) or -1),
        })
        self.appearances.extend(rows_app)
        self.innings.extend(rows_inn)
        self.deliveries[scope].extend(rows_del)
        self.wickets.extend(rows_wk)
        self.batting.extend(rows_bat)
        self.bowling.extend(rows_bowl)
        self.counts[scope] += 1
        if len(self.deliveries[scope]) >= self.flush_rows:
            self._flush(scope)

    # ----------------------------------------------------------------- output
    def _flush(self, scope: str) -> None:
        buf = self.deliveries[scope]
        if not len(buf):
            return
        table = buf.table()
        w = self.writers.get(scope)
        if w is None:
            w = self.writers[scope] = pq.ParquetWriter(self.out / "deliveries" / f"{scope}.parquet",
                                                       table.schema, compression="zstd")
        w.write_table(table)
        buf.clear()

    def finish(self) -> None:
        for scope in list(self.deliveries):
            self._flush(scope)
        for w in self.writers.values():
            w.close()
        pq.write_table(pa.Table.from_pylist(self.matches), self.out / "matches.parquet", compression="zstd")
        pq.write_table(self.players.table(), self.out / "players.parquet", compression="zstd")
        for name, buf in (("wickets", self.wickets), ("batting", self.batting),
                          ("bowling", self.bowling), ("appearances", self.appearances),
                          ("innings", self.innings)):
            pq.write_table(buf.table(), self.out / f"{name}.parquet", compression="zstd")


def match_number(stem: str) -> int | None:
    """Cricsheet ids are numeric; a few domestic files use a prefix (``wi_201706``).
    Prefixed ids map into a reserved range above every numeric Cricsheet id."""
    if stem.isdigit():
        return int(stem)
    m = re.fullmatch(r"([a-z]{1,4})_(\d{1,8})", stem)
    if not m:
        return None
    return 2_000_000_000 + (sum(map(ord, m.group(1))) % 100) * 1_000_000 + int(m.group(2)) % 1_000_000


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def build_warehouse(archive: str | Path, out: str | Path, competitions: str | Path,
                    *, limit: int | None = None, progress=None) -> dict:
    """Ingest a Cricsheet JSON zip into ``out``. Returns the build manifest."""
    archive, out = Path(archive), Path(out)
    out.mkdir(parents=True, exist_ok=True)
    for old in list((out / "deliveries").glob("*.parquet")) if (out / "deliveries").exists() else []:
        old.unlink()
    started = time.time()
    wh = Warehouse(out, load_competitions(competitions))
    with zipfile.ZipFile(archive) as z:
        members = [m for m in z.infolist() if m.filename.endswith(".json") and not m.is_dir()]
        if sum(m.file_size for m in members) > MAX_ARCHIVE_BYTES:
            raise ValueError("expanded archive exceeds the safety limit")
        if limit:
            members = members[:limit]
        seen = set()
        for i, m in enumerate(members):
            path = PurePosixPath(m.filename)
            if path.is_absolute() or ".." in path.parts or m.file_size > MAX_MEMBER_BYTES:
                raise ValueError(f"unsafe or oversized archive member {m.filename}")
            mid = match_number(path.stem)
            if mid is None:
                wh.quarantine.append({"file": m.filename, "error": "unrecognised match identifier"})
                continue
            if mid in seen:
                raise ValueError(f"duplicate match identifier {mid}")
            seen.add(mid)
            try:
                wh.add_match(mid, z.read(m), path.stem)
            except (ValueError, KeyError, TypeError, AttributeError) as exc:
                wh.quarantine.append({"file": m.filename, "error": str(exc)[:300]})
            if progress and i % 2000 == 0:
                progress(i, len(members))
    wh.finish()
    manifest = {
        "source": {"path": archive.name, "sha256": file_sha256(archive),
                   "bytes": archive.stat().st_size, "members": len(members)},
        "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "seconds": round(time.time() - started, 1),
        "matches": sum(wh.counts.values()), "by_scope": dict(sorted(wh.counts.items())),
        "players": len(wh.players.ids), "quarantined": len(wh.quarantine),
        "quarantine": wh.quarantine,
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest
