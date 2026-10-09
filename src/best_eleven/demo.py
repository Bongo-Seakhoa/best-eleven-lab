"""Seeded fictional cricket. Demo records can never enter the real-data scope."""
from __future__ import annotations
from datetime import date, timedelta
from hashlib import sha256
import json
import random
from .ingest import ingest_match
from .metadata import FIELDS

DEMO_LABEL = "SYNTHETIC: invented players, teams and outcomes; seed=42"
TEAM_NAMES = ["Cedar XI (demo)", "Indigo XI (demo)", "Ochre XI (demo)", "Silver XI (demo)"]
FIRST = ["Ari", "Noah", "Kai", "Leon", "Mika", "Eli", "Ravi", "Tari", "Luca", "Adam", "Owen", "Zion", "Jai", "Theo", "Finn", "Amir"]
LAST = ["Rowan", "Vale", "Reed", "Brooks"]
ROLES = ["opener", "opener", "bat", "bat", "bat", "keeper", "all_rounder", "bowler", "bowler", "bowler", "bowler", "bowler", "all_rounder", "bat", "opener", "keeper"]
STYLES = [None] * 6 + ["right-arm off spin", "right-arm fast", "left-arm fast", "right-arm leg spin", "slow left-arm orthodox", "right-arm medium", "right-arm medium", None, None, None]


def make_demo(db, matches_per_format=36):
    if not 6 <= matches_per_format <= 100:
        raise ValueError("Use 6–100 demo matches per format")
    rng = random.Random(42)
    players = {team: [f"{first} {LAST[t]}" for first in FIRST] for t, team in enumerate(TEAM_NAMES)}
    registry = {name: sha256(("best-eleven-fiction-" + name).encode()).hexdigest()[:8] for names in players.values() for name in names}
    statuses = {"inserted": 0, "updated": 0, "unchanged": 0}
    for fi, fmt in enumerate(("Test", "ODI", "T20")):
        for game in range(matches_per_format):
            t1 = TEAM_NAMES[game % 4]
            t2 = TEAM_NAMES[(game % 4 + 1 + (game // 4) % 3) % 4]
            rosters = {}
            for team in (t1, t2):
                roster = players[team][:11]
                if game % 4 == 0:
                    roster[7] = players[team][11]
                if game > matches_per_format // 2 and game % 3 == 0:
                    roster[6], roster[4] = players[team][12], players[team][13]
                if game > matches_per_format * .65 and game % 2 == 0:
                    roster[1] = players[team][14]
                if game % 6 == 0:
                    roster[5] = players[team][15]
                rosters[team] = roster
            day = date(2018, 2, 1) + timedelta(days=75 * game + 7 * fi)
            innings, prior = [], {t1: 0, t2: 0}
            n_innings = 4 if fmt == "Test" else 2
            max_overs = {"Test": 65, "ODI": 50, "T20": 20}[fmt]
            for inn in range(n_innings):
                bt, qt = (t1, t2)[inn % 2], (t2, t1)[inn % 2]
                batters, fielders = rosters[bt], rosters[qt]
                bowling = fielders[6:11]
                striker, nonstriker, next_batter = 0, 1, 2
                overs, total, fallen = [], 0, 0
                target = prior[qt] - prior[bt] + 1 if inn == n_innings - 1 else None
                if target is not None and target <= 0:
                    break
                for over in range(max_overs):
                    bowler = bowling[over % 5]
                    balls, legal = [], 0
                    while legal < 6 and fallen < 10 and (target is None or total < target):
                        name = batters[striker]
                        pos = players[bt].index(name)
                        bowler_pos = players[qt].index(bowler)
                        probability = {"Test": .032, "ODI": .035, "T20": .049}[fmt]
                        probability *= 1.7 if ROLES[pos] == "bowler" else 1
                        probability *= .66 if pos in (2, 13) else 1
                        probability *= 1.25 if bowler_pos in (8, 9) else 1
                        probability *= 1.3 if pos == 0 and game > matches_per_format * .65 else 1
                        ex, noise = {}, rng.random()
                        if noise < .019:
                            ex["wides"] = 1
                        elif noise < .029:
                            ex["noballs"] = 1
                        elif noise < .045:
                            ex["legbyes"] = 1
                        probs = {"Test": [.60, .24, .045, .005, .10, .01], "ODI": [.42, .35, .08, .01, .12, .02], "T20": [.32, .36, .08, .01, .17, .06]}[fmt]
                        if ROLES[pos] == "bowler":
                            probs = [p * (.65 if i in (4, 5) else 1.1) for i, p in enumerate(probs)]
                        if pos in (4, 14):
                            probs = [p * (1.4 if i in (4, 5) else .93) for i, p in enumerate(probs)]
                        runs = rng.choices([0, 1, 2, 3, 4, 6], probs)[0] if not ex.get("wides") and not ex.get("legbyes") else 0
                        out = not (ex.get("wides") or ex.get("noballs")) and rng.random() < probability
                        ball = {"batter": name, "non_striker": batters[nonstriker], "bowler": bowler,
                                "runs": {"batter": runs, "extras": sum(ex.values()), "total": runs + sum(ex.values())}}
                        if ex:
                            ball["extras"] = ex
                        if out:
                            kind = rng.choices(["caught", "bowled", "lbw", "stumped", "run out"], [50, 22, 17, 7, 4])[0]
                            ball["runs"] = {"batter": 0, "extras": 0, "total": 0}
                            ball.pop("extras", None)
                            ex, runs = {}, 0
                            detail = {"kind": kind, "player_out": name}
                            if kind in {"caught", "run out", "stumped"}:
                                detail["fielders"] = [{"name": fielders[5] if kind == "stumped" else rng.choice(fielders)}]
                            ball["wickets"] = [detail]
                            fallen += 1
                        balls.append(ball)
                        total += ball["runs"]["total"]
                        if not (ex.get("wides") or ex.get("noballs")):
                            legal += 1
                        if out and fallen < 10:
                            striker, next_batter = next_batter, next_batter + 1
                        elif (runs + ex.get("byes", 0) + ex.get("legbyes", 0)) % 2:
                            striker, nonstriker = nonstriker, striker
                    overs.append({"over": over, "deliveries": balls})
                    striker, nonstriker = nonstriker, striker
                    if fallen >= 10 or (target is not None and total >= target):
                        break
                item = {"team": bt, "overs": overs}
                if target is not None:
                    item["target"] = {"runs": target}
                if fmt == "Test" and fallen < 10 and inn < 3:
                    item["declared"] = True
                innings.append(item)
                prior[bt] += total
            doc = {"meta": {"data_version": "1.1.0", "created": "2026-10-09", "revision": 1},
                "info": {"balls_per_over": 6, "dates": [day.isoformat(), (day + timedelta(days=3)).isoformat()] if fmt == "Test" else [day.isoformat()],
                         "gender": "male", "match_type": fmt, "team_type": "international", "season": day.year,
                         "teams": [t1, t2], "players": rosters, "registry": {"people": registry},
                         "venue": ["Fictional North Ground", "Fictional Valley Oval", "Fictional Coast Park"][game % 3]},
                "innings": innings, "synthetic_notice": DEMO_LABEL}
            status = ingest_match(db, f"demo_{fmt}_{game:03d}", json.dumps(doc).encode(), "demo_seed42", DEMO_LABEL, synthetic=True)
            statuses[status] = statuses.get(status, 0) + 1
    with db:
        for team in TEAM_NAMES:
            for pos, name in enumerate(players[team]):
                for fmt in ("Test", "ODI", "T20"):
                    rec = {"player_id": registry[name], "format": fmt, "level": "international", "valid_from": "2018-01-01", "valid_to": None,
                        "role": ROLES[pos], "batting_hand": "left" if pos % 3 == 0 else "right", "bowling_style": STYLES[pos], "team": team,
                        "captain_matches": 16 if pos == 2 else 0, "vice_captain_matches": 12 if pos == 0 else 0,
                        "credit": 9.5 if pos in (2, 8, 9) else 8.0, "available": 1,
                        "source_url": "https://example.invalid/best-eleven/synthetic-seed42", "observed_at": "2025-08-01"}
                    db.execute("INSERT OR REPLACE INTO metadata VALUES (" + ",".join("?" * len(FIELDS)) + ")", tuple(rec[k] for k in FIELDS))
    return {"status": "ok", "provenance": DEMO_LABEL, **statuses}
