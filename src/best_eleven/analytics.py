"""Format-specific evidence and transparent heuristics, not a claim to universal ability."""
from __future__ import annotations
from dataclasses import dataclass, asdict
from datetime import date
import math
import numpy as np
import pandas as pd
from .store import rows

@dataclass(frozen=True)
class Scope:
    format: str = "Test"
    gender: str = "male"
    level: str = "international"
    competition: str = ""
    team: str = ""
    since: str = "2000-01-01"
    as_of: str = "2026-10-09"
    dataset: str = "real"
    half_life_days: float = 730.0

    def __post_init__(self):
        if self.format not in {"Test", "ODI", "T20"}:
            raise ValueError("Select Test, ODI or T20")
        if self.gender not in {"male", "female"} or self.level not in {"international", "club"}:
            raise ValueError("Invalid population")
        if self.dataset not in {"real", "demo"}:
            raise ValueError("Real and synthetic data must remain separate")
        if date.fromisoformat(self.since) >= date.fromisoformat(self.as_of):
            raise ValueError("Start date must precede the exclusive as-of date")
        if not math.isfinite(self.half_life_days) or self.half_life_days < 0:
            raise ValueError("Half life must be non-negative; zero disables decay")

    def where(self, alias="m"):
        terms = [f"{alias}.format=?", f"{alias}.gender=?", f"{alias}.level=?", f"{alias}.start_date>=?", f"{alias}.end_date<?", f"{alias}.is_synthetic=?"]
        args = [self.format, self.gender, self.level, self.since, self.as_of, int(self.dataset == "demo")]
        if self.competition:
            terms.append(f"{alias}.competition=?")
            args.append(self.competition)
        return " AND ".join(terms), args


def metadata_at(db, scope: Scope) -> dict:
    result = {}
    for r in rows(db, """SELECT * FROM metadata WHERE format=? AND level=? AND valid_from<?
             AND (valid_to IS NULL OR valid_to>=?) AND observed_at<? ORDER BY observed_at,valid_from,source_url""",
             (scope.format, scope.level, scope.as_of, scope.as_of, scope.as_of)):
        result[r["player_id"]] = r
    return result


def weighted(frame, scope):
    if frame.empty:
        return frame
    frame = frame.copy()
    age = (pd.Timestamp(scope.as_of) - pd.to_datetime(frame.end_date)).dt.days
    frame["weight"] = np.exp2(-age / scope.half_life_days) if scope.half_life_days else 1.0
    frame["era"] = (pd.to_datetime(frame.end_date).dt.year // 5 * 5).astype(str)
    return frame


def evidence_frames(db, scope):
    where, args = scope.where()
    bat = pd.read_sql_query(f"""SELECT b.*,m.end_date,m.competition,m.season,i.batting_team AS team
        FROM batting b JOIN matches m ON m.id=b.match_id JOIN innings i ON i.match_id=b.match_id AND i.number=b.innings
        WHERE {where} AND i.super_over=0""", db, params=args)
    if len(bat):
        bat["band"] = np.select([bat.position <= 2, bat.position <= 5, bat.position <= 7], ["Opening", "Middle order", "Lower middle"], default="Tail")
    bowl = pd.read_sql_query(f"""SELECT d.match_id,d.innings,d.bowler AS player_id,m.end_date,m.competition,m.season,
        i.bowling_team AS team,SUM(d.legal_ball) AS balls,SUM(d.conceded) AS conceded,SUM(d.bowler_wickets) AS wickets,
        SUM(d.total_runs=0 AND d.legal_ball=1) AS dots,SUM(d.boundary4+d.boundary6) AS boundaries,COUNT(*) AS deliveries
        FROM deliveries d JOIN matches m ON m.id=d.match_id JOIN innings i ON i.match_id=d.match_id AND i.number=d.innings
        WHERE {where} AND i.super_over=0 GROUP BY d.match_id,d.innings,d.bowler""", db, params=args)
    app = pd.read_sql_query(f"SELECT a.*,m.end_date FROM appearances a JOIN matches m ON m.id=a.match_id WHERE {where}", db, params=args)
    return weighted(bat, scope), weighted(bowl, scope), weighted(app, scope)


def ratio(n, d):
    return float(n / d) if d > 0 else None


def score(index):
    return float(50 + 30 * np.tanh(np.log(max(index, .001)) / .65))


class Benchmarks:
    """Subtract the player's own evidence from grouped aggregates in O(1) per cell."""
    def __init__(self, frame, cols, keys):
        self.cols, self.keys = cols, keys
        if frame.empty:
            self.total = np.zeros(len(cols) + 2)
            self.cells = self.people = self.personal_cells = {}
            return
        w = frame.copy()
        for c in cols:
            w[c] = w[c] * w.weight
        # Raw counts govern fallback, while weighted counts determine peer rates.
        w["raw_balls"] = frame.balls
        w["raw_events"] = frame["outs" if "outs" in frame else "wickets"]
        self.vcols = cols + ["raw_balls", "raw_events"]
        self.total = w[self.vcols].sum().to_numpy(float)
        self.cells = {k if isinstance(k, tuple) else (k,): v.to_numpy(float) for k, v in w.groupby(keys)[self.vcols].sum().iterrows()}
        self.personal_cells = {k: v.to_numpy(float) for k, v in w.groupby(["player_id"] + keys)[self.vcols].sum().iterrows()}
        self.people = {k: v.to_numpy(float) for k, v in w.groupby("player_id")[self.vcols].sum().iterrows()}

    def peers(self, player, cell):
        zero = np.zeros(len(self.cols) + 2)
        peer = self.cells.get(cell, zero) - self.personal_cells.get((player,) + cell, zero)
        fallback = peer[-2] < 200 or peer[-1] < 10
        if fallback:
            peer = self.total - self.people.get(player, zero)
        return peer[:len(self.cols)], fallback


def rankings(db, scope: Scope) -> dict:
    bat, bowl, app = evidence_frames(db, scope)
    if app.empty:
        return {"scope": asdict(scope), "players": [], "matches": 0, "warnings": ["No records match this scope. Fetch or import data first."]}
    md_all = metadata_at(db, scope)
    names = dict(db.execute("SELECT id,name FROM players"))
    app_selected = app[app.team == scope.team] if scope.team else app
    bat_selected = bat[bat.team == scope.team] if scope.team and len(bat) else bat
    bowl_selected = bowl[bowl.team == scope.team] if scope.team and len(bowl) else bowl
    bat_groups = dict(tuple(bat_selected.groupby("player_id"))) if len(bat_selected) else {}
    bowl_groups = dict(tuple(bowl_selected.groupby("player_id"))) if len(bowl_selected) else {}
    app_groups = dict(tuple(app_selected.groupby("player_id")))
    bb = Benchmarks(bat, ["runs", "balls", "outs"], ["era", "competition", "band"])
    qb = Benchmarks(bowl, ["conceded", "balls", "wickets"], ["era", "competition"])
    where, args = scope.where()
    keepers = set(r[0] for r in db.execute(f"""SELECT DISTINCT f.player_id FROM fielding f JOIN matches m ON m.id=f.match_id
        JOIN innings i ON i.match_id=f.match_id AND i.number=f.innings WHERE {where} AND i.super_over=0 AND f.kind='stumped'""", args))
    result = []
    pace_weight = {"Test": .20, "ODI": .45, "T20": .65}[scope.format]
    prior_balls = {"Test": 360, "ODI": 240, "T20": 120}[scope.format]
    for p, appearances in app_groups.items():
        b, q = bat_groups.get(p, bat.iloc[:0]), bowl_groups.get(p, bowl.iloc[:0])
        a = appearances.drop_duplicates("match_id")
        md = md_all.get(p, {})
        bf, runs_, outs = (float(b[c].sum()) if len(b) else 0.0 for c in ("balls", "runs", "outs"))
        legal, conc, wk = (float(q[c].sum()) if len(q) else 0.0 for c in ("balls", "conceded", "wickets"))
        bs = qs = 0.0
        rate_index = avg_index = econ_index = wicket_index = None
        fallback_count = 0
        if bf:
            exp_rate = exp_avg = weight_sum = 0.0
            for key, cell in b.groupby(bb.keys):
                (pr, pb, po), fallback = bb.peers(p, key)
                fallback_count += int(fallback)
                cw = float((cell.balls * cell.weight).sum())
                if min(pr, pb, po, cw) > 0:
                    exp_rate += cw * pr / pb
                    exp_avg += cw * pr / po
                    weight_sum += cw
            if weight_sum:
                base_r, base_avg = exp_rate / weight_sum, exp_avg / weight_sum
                wr, wb, wo = (float((b[c] * b.weight).sum()) for c in ("runs", "balls", "outs"))
                rate_index = (wr + prior_balls * base_r) / ((wb + prior_balls) * base_r)
                avg_index = (wr + 5 * base_avg) / ((wo + 5) * base_avg)
                bs = pace_weight * score(rate_index) + (1 - pace_weight) * score(avg_index)
        if legal:
            exp_runs = exp_wk = weight_sum = 0.0
            for key, cell in q.groupby(qb.keys):
                (pc, pb, pw), fallback = qb.peers(p, key)
                fallback_count += int(fallback)
                cw = float((cell.balls * cell.weight).sum())
                if min(pc, pb, pw, cw) > 0:
                    exp_runs += cw * pc / pb
                    exp_wk += cw * pw / pb
                    weight_sum += cw
            if weight_sum:
                base_r, base_w = exp_runs / weight_sum, exp_wk / weight_sum
                wc, wb, ww = (float((q[c] * q.weight).sum()) for c in ("conceded", "balls", "wickets"))
                econ_index = base_r / ((wc + prior_balls * base_r) / (wb + prior_balls))
                wicket_index = ((ww + prior_balls * base_w) / (wb + prior_balls)) / base_w
                wwgt = .75 if scope.format == "Test" else .55
                qs = (1 - wwgt) * score(econ_index) + wwgt * score(wicket_index)
        position = float(b.position.median()) if len(b) else None
        opening_share = float((b.position <= 2).mean()) if len(b) else 0.0
        batting_cap = bf >= {"Test": 120, "ODI": 90, "T20": 45}[scope.format] and position <= 7
        bowling_cap = legal >= {"Test": 240, "ODI": 120, "T20": 60}[scope.format]
        roles = (["bat"] if batting_cap else []) + (["opener"] if batting_cap and opening_share >= .35 else []) + (["bowler"] if bowling_cap else [])
        if batting_cap and bowling_cap:
            roles.append("all_rounder")
        if p in keepers:
            roles.extend(["keeper", "bat"])
        origin = "Inferred from usage; keeper only from stumping evidence"
        if md.get("role"):
            roles = {"opener": ["opener", "bat"], "bat": ["bat"], "keeper": ["keeper", "bat"], "all_rounder": ["all_rounder", "bat", "bowler"], "bowler": ["bowler"]}[md["role"]]
            origin = "Synthetic metadata" if scope.dataset == "demo" else "Sourced metadata"
        weights = a.weight.to_numpy()
        ess = float(weights.sum() ** 2 / np.square(weights).sum()) if np.square(weights).sum() else 0.0
        cap, vc = md.get("captain_matches"), md.get("vice_captain_matches")
        leadership = None if cap is None or vc is None else min(100.0, 100 * math.log1p(cap + .5 * vc) / math.log1p(100))
        result.append({"id": p, "name": names.get(p, p), "teams": sorted(a.team.unique()), "matches": len(a), "innings": len(b),
            "runs": int(runs_), "balls_faced": int(bf), "outs": int(outs), "average": ratio(runs_, outs), "strike_rate": ratio(100 * runs_, bf),
            "legal_balls": int(legal), "conceded": int(conc), "wickets": int(wk), "economy": ratio(6 * conc, legal),
            "bowling_average": ratio(conc, wk), "bowling_strike_rate": ratio(legal, wk), "batting_score": round(bs, 4), "bowling_score": round(qs, 4),
            "average_index": avg_index, "scoring_rate_index": rate_index, "economy_index": econ_index, "wicket_rate_index": wicket_index,
            "experience_score": min(100.0, 100 * math.log1p(len(a)) / math.log1p(150)), "leadership_score": leadership,
            "effective_matches": ess, "median_position": position, "opening_share": opening_share, "roles": sorted(set(roles)),
            "role_evidence": origin, "role_source": md.get("source_url"), "batting_hand": md.get("batting_hand"), "bowling_style": md.get("bowling_style"),
            "credit": md.get("credit"), "available": md.get("available"), "metadata_team": md.get("team"),
            "first_observed": str(a.end_date.min()), "last_observed": str(a.end_date.max()), "fallback_cells": fallback_count})
    result.sort(key=lambda r: (-max(r["batting_score"], r["bowling_score"]), r["id"]))
    warnings = ["Available-record comparison, not complete-career or all-time coverage.",
                "Quality is a declared shrinkage heuristic, not a validated probability of winning. Peer adjustment does not fully control opposition or conditions.",
                "Roster appearances do not establish current eligibility, fitness or starting-XI status.",
                "Leadership counts documented appointments, not their effectiveness. Unknown is not zero."]
    if scope.dataset == "demo":
        warnings.insert(0, "SYNTHETIC DEMONSTRATION: every displayed player and outcome is invented.")
    if not scope.team:
        warnings.append("Mixed-team pool. Choose a country for a national-team XI.")
    return {"scope": asdict(scope), "players": result, "matches": int(app_selected.match_id.nunique()),
            "benchmark_matches": int(app.match_id.nunique()), "first_match": str(app_selected.end_date.min()) if len(app_selected) else None,
            "last_match": str(app_selected.end_date.max()) if len(app_selected) else None, "warnings": warnings}


def bootstrap_ratio(frame, numerator, denominator, multiplier=1.0, repetitions=250, seed=17):
    if frame.empty:
        return {"low": None, "high": None, "clusters": 0, "undefined_fraction": None}
    g = frame.groupby("match_id")[[numerator, denominator]].sum().to_numpy(float)
    if len(g) < 3:
        return {"low": None, "high": None, "clusters": len(g), "undefined_fraction": None}
    rng = np.random.default_rng(seed)
    sums = g[rng.integers(0, len(g), (repetitions, len(g)))].sum(axis=1)
    ok = sums[:, 1] > 0
    vals = multiplier * sums[ok, 0] / sums[ok, 1]
    low, high = np.quantile(vals, [.025, .975]) if len(vals) else (None, None)
    return {"low": float(low) if low is not None else None, "high": float(high) if high is not None and ok.mean() >= .975 else None,
            "clusters": len(g), "undefined_fraction": float(1 - ok.mean()),
            "method": "95% percentile interval; 250 match-cluster bootstrap samples. Not simultaneous intervals."}


def player_profile(db, scope: Scope, player_id: str, ranking=None):
    ranking = ranking or rankings(db, scope)
    player = next((p for p in ranking["players"] if p["id"] == player_id), None)
    if player is None:
        raise ValueError("Player is outside this candidate pool")
    where, args = scope.where()
    f = pd.read_sql_query(f"""SELECT d.*,m.end_date,m.season,m.venue,i.batting_team,i.bowling_team,b.position
        FROM deliveries d JOIN matches m ON m.id=d.match_id JOIN innings i ON i.match_id=d.match_id AND i.number=d.innings
        LEFT JOIN batting b ON b.match_id=d.match_id AND b.innings=d.innings AND b.player_id=d.batter
        WHERE {where} AND i.super_over=0 AND (d.batter=? OR d.bowler=?)""", db, params=args + [player_id, player_id])
    names = dict(db.execute("SELECT id,name FROM players"))
    md = metadata_at(db, scope)
    bat = f[f.batter == player_id].copy() if len(f) else f.copy()
    bowl = f[f.bowler == player_id].copy() if len(f) else f.copy()
    if scope.team:
        bat = bat[bat.batting_team == scope.team]
        bowl = bowl[bowl.bowling_team == scope.team]
    if len(bat):
        bat["opponent"] = bat.bowling_team
        bat["style"] = bat.bowler.map(lambda p: md.get(p, {}).get("bowling_style") or "Unknown bowling style")
    if len(bowl):
        bowl["opponent"] = bowl.batting_team
        bowl["hand"] = bowl.batter.map(lambda p: md.get(p, {}).get("batting_hand") or "Unknown batting hand")
        bowl["band"] = np.select([bowl.position <= 2, bowl.position <= 5, bowl.position <= 7], ["Openers", "Middle order", "Lower middle"], default="Tail")
    def splits(frame, group, bowling=False):
        result = []
        if frame.empty:
            return result
        for key, g in frame.groupby(group, dropna=False):
            n, legal, faced = len(g), int(g.legal_ball.sum()), int(g.faced_ball.sum())
            wickets = int(g.striker_wickets.sum())
            label = names.get(key, str(key)) if group in {"bowler", "batter"} else str(key)
            numerator, denom, mult = ("conceded", "legal_ball", 6) if bowling else ("bat_runs", "faced_ball", 100)
            result.append({"label": label, "group_id": str(key), "deliveries": n, "legal_balls": legal, "balls_faced": faced,
                "matches": int(g.match_id.nunique()), "runs": int(g.bat_runs.sum()), "conceded": int(g.conceded.sum()),
                "dismissals_to_bowler": wickets, "wickets_per_100_deliveries": 100 * wickets / n,
                "strike_rate": ratio(100 * g.bat_runs.sum(), faced), "economy": ratio(6 * g.conceded.sum(), legal),
                "boundary_pct": ratio(100 * (g.boundary4 + g.boundary6).sum(), faced),
                "scoreless_legal_pct": ratio(100 * ((g.total_runs == 0) & (g.legal_ball == 1)).sum(), legal),
                "evidence": "Sparse: explore, do not conclude" if n < 60 or g.match_id.nunique() < 5 else "Descriptive, not causal",
                "interval": bootstrap_ratio(g, numerator, denom, mult)})
        return sorted(result, key=lambda r: (-r["deliveries"], r["group_id"]))
    team_clause, team_args = (" AND i.batting_team=?", [scope.team]) if scope.team else ("", [])
    dismissals = rows(db, f"""SELECT w.kind,COUNT(*) AS count FROM wickets w JOIN matches m ON m.id=w.match_id
        JOIN innings i ON i.match_id=w.match_id AND i.number=w.innings WHERE {where} AND i.super_over=0
        AND w.player_out=? AND w.is_out=1 {team_clause} GROUP BY w.kind ORDER BY count DESC""", args + [player_id] + team_args)
    bf, qf, _ = evidence_frames(db, scope)
    personal_bat = bf[bf.player_id == player_id] if len(bf) else bf
    personal_bowl = qf[qf.player_id == player_id] if len(qf) else qf
    if scope.team:
        personal_bat = personal_bat[personal_bat.team == scope.team]
        personal_bowl = personal_bowl[personal_bowl.team == scope.team]
    return {"player": player, "scope": asdict(scope),
        "batting": {k: splits(bat, v) for k, v in {"opponents": "opponent", "matchups": "bowler", "styles": "style", "phases": "phase", "venues": "venue", "trend": "season"}.items()},
        "bowling": {k: splits(bowl, v, True) for k, v in {"opponents": "opponent", "matchups": "batter", "hands": "hand", "archetypes": "band", "phases": "phase", "venues": "venue", "trend": "season"}.items()},
        "dismissals": dismissals, "uncertainty": {"batting_average": bootstrap_ratio(personal_bat, "runs", "outs"), "bowling_economy": bootstrap_ratio(personal_bowl, "conceded", "balls", 6)},
        "spatial": {"status": "unavailable", "recommendations": [], "reason": "Standard Cricsheet JSON does not locate shots or every fielder. Catcher identity is not catch location, and dots are not measured runs saved.",
                    "required": ["Every delivery, including dots, boundaries and misses", "Pre-delivery positions of all fielders", "Shot direction, height, trajectory and outcome", "Delivery line, length, pace, handedness and game state", "A defensible way to handle non-random field choice and unobserved confounding"]},
        "warnings": ["All exposures remain in matchup denominators, including bowlers who never dismissed the batter. Dismissal-type charts describe dismissals only.",
                     "Observed associations are not causal weaknesses. Field, opponent, pitch and game state are not random.",
                     "Match bootstrap intervals do not fully capture dependence across matches or multiple testing.",
                     "Over bands are not official powerplays; Test over bands are not ball age. Batting-order archetypes are observed roles, not stroke-technique labels."]}


def coverage(db):
    return {"groups": rows(db, """SELECT format,gender,level,competition,is_synthetic,COUNT(*) AS matches,MIN(start_date) AS first_date,
        MAX(end_date) AS last_date,SUM(missing_json!='[]') AS metadata_flagged_matches FROM matches
        GROUP BY format,gender,level,competition,is_synthetic ORDER BY level DESC,format"""),
        "teams": rows(db, "SELECT DISTINCT a.team,m.level,m.gender,m.is_synthetic FROM appearances a JOIN matches m ON m.id=a.match_id ORDER BY a.team"),
        "deliveries": db.execute("SELECT COUNT(*) FROM deliveries").fetchone()[0],
        "players": db.execute("SELECT COUNT(DISTINCT player_id) FROM appearances").fetchone()[0],
        "fetches": rows(db, "SELECT source_key,url,fetched_at,match_count,status,sha256 FROM fetches"),
        "errors": rows(db, "SELECT source_key,file_name,error,recorded_at FROM ingestion_errors ORDER BY id DESC LIMIT 20"),
        "source_coverage": "Completeness against all scheduled fixtures is unverified. Informational missing flags (umpires, reviews, awards or powerplays) do not discard valid deliveries."}
