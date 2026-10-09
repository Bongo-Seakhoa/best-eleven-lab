"""Role-constrained integer optimisation and auditable preference sensitivity."""
from __future__ import annotations
from dataclasses import dataclass, asdict
import math
import numpy as np
from scipy.optimize import milp, Bounds, LinearConstraint

@dataclass(frozen=True)
class Preferences:
    performance: float = 85.0
    experience: float = 15.0
    leadership: float = 0.0
    sampling_caution: float = 0.0
    min_matches: int = 5
    min_bowling_options: int = 5
    min_batting_options: int = 6
    min_openers: int = 2
    min_pace: int = 0
    min_spin: int = 0
    require_sourced_roles: bool = False
    require_available: bool = False
    budget: float | None = None
    max_from_team: int | None = None

    def __post_init__(self):
        for k in ("performance", "experience", "leadership", "sampling_caution"):
            value = getattr(self, k)
            if not math.isfinite(value) or value < 0:
                raise ValueError(f"{k} must be finite and non-negative")
        if not self.performance + self.experience + self.leadership:
            raise ValueError("At least one preference weight must be positive")
        if self.sampling_caution > 1:
            raise ValueError("Sampling caution must be between 0 and 1")
        for k in ("min_bowling_options", "min_batting_options", "min_openers", "min_pace", "min_spin", "min_matches"):
            v = getattr(self, k)
            if not isinstance(v, int) or isinstance(v, bool) or v < 0:
                raise ValueError(f"{k} must be a non-negative integer")
        if self.min_openers > 2 or max(self.min_batting_options, self.min_bowling_options, self.min_pace, self.min_spin) > 11:
            raise ValueError("Role requirements exceed XI capacity")
        if self.budget is not None and (not math.isfinite(self.budget) or self.budget <= 0):
            raise ValueError("Budget must be positive")
        if self.max_from_team is not None and (not isinstance(self.max_from_team, int) or isinstance(self.max_from_team, bool) or not 1 <= self.max_from_team <= 11):
            raise ValueError("Team limit must be 1–11")


def slot_quality(player, slot):
    if slot in {"opener", "bat", "keeper"}:
        return player["batting_score"]
    if slot == "bowler":
        return player["bowling_score"]
    return max(player["batting_score"] if "bat" in player["roles"] else 0, player["bowling_score"] if "bowler" in player["roles"] else 0)


def bowling_family(player):
    style = (player.get("bowling_style") or "").lower()
    if "bowler" not in player["roles"]:
        return None
    if any(x in style for x in ("spin", "orthodox", "break")):
        return "spin"
    if any(x in style for x in ("fast", "medium", "pace", "seam")):
        return "pace"
    return None


def select_eleven(ranking, preferences=None, *, locked=None, excluded=None, fantasy_values=None):
    pref = preferences or Preferences(min_bowling_options=4 if ranking.get("scope", {}).get("format") == "Test" else 5)
    locked, excluded = set(locked or []), set(excluded or [])
    if locked & excluded:
        raise ValueError("A player cannot be locked and excluded")
    if len(locked) > 11:
        raise ValueError("More than eleven players are locked")
    team = ranking.get("scope", {}).get("team")
    pool = [r for r in ranking["players"] if r["id"] not in excluded and r["matches"] >= pref.min_matches
            and (not pref.require_sourced_roles or r["role_evidence"] in {"Sourced metadata", "Synthetic metadata"})
            and (not pref.require_available or (r["available"] == 1 and (not team or r.get("metadata_team") == team)))]
    pool.sort(key=lambda r: r["id"])
    ids = {r["id"] for r in pool}
    if locked - ids:
        raise ValueError("A locked player is outside the eligible pool")
    if pref.leadership and any(r["leadership_score"] is None for r in pool):
        raise ValueError("Leadership weighting needs dated appointment counts for every candidate. Unknown is not zero.")
    if pref.budget is not None and any(r["credit"] is None for r in pool):
        raise ValueError("Budget selection needs credits for every candidate")
    if pref.max_from_team is not None and any(len(r["teams"]) != 1 for r in pool):
        raise ValueError("Team limits need one unambiguous team per candidate in this evidence window")
    if fantasy_values is not None and ids - fantasy_values.keys():
        raise ValueError("Every candidate needs a fantasy projection")
    slots = ["opener"] * pref.min_openers + ["bat"] * (5 - pref.min_openers) + ["keeper", "flex"] + ["bowler"] * 4
    choices = []
    weight_sum = pref.performance + pref.experience + pref.leadership
    for i, player in enumerate(pool):
        for s, slot in enumerate(slots):
            if slot not in player["roles"] and not (slot == "flex" and ({"bat", "bowler"} & set(player["roles"]))):
                continue
            quality = slot_quality(player, slot)
            if quality <= 0:
                continue  # No evidence for the discipline cannot fill a specialist slot.
            parts = {"performance": pref.performance * quality / weight_sum,
                     "experience": pref.experience * player["experience_score"] / weight_sum,
                     "leadership": pref.leadership * (player["leadership_score"] or 0) / weight_sum,
                     "sampling_penalty": pref.sampling_caution * 15 / math.sqrt(1 + player["effective_matches"] / 10)}
            value = parts["performance"] + parts["experience"] + parts["leadership"] - parts["sampling_penalty"]
            if fantasy_values is not None:
                value = float(fantasy_values[player["id"]])
                if not math.isfinite(value):
                    raise ValueError("Fantasy projections must be finite")
            choices.append((i, s, value, parts))
    base = {"scope": ranking.get("scope", {}), "preferences": asdict(pref), "candidate_count": len(pool), "status": "infeasible", "eleven": [],
            "objective": "Historical mean fantasy points" if fantasy_values is not None else "Role-specific quality plus explicit preferences",
            "warnings": list(ranking.get("warnings", []))}
    if len(pool) < 11 or not choices:
        return {**base, "reason": "Fewer than eleven eligible candidates or no role-compatible assignments. Fetch more records or review the constraints."}
    matrix, lower, upper = [], [], []
    def add(row, lo, hi):
        matrix.append(row); lower.append(lo); upper.append(hi)
    for s in range(11):
        add([int(j == s) for i, j, u, c in choices], 1, 1)
    for i, player in enumerate(pool):
        add([int(k == i) for k, j, u, c in choices], int(player["id"] in locked), 1)
    add([int("bowler" in pool[i]["roles"]) for i, j, u, c in choices], pref.min_bowling_options, 11)
    add([int("bat" in pool[i]["roles"]) for i, j, u, c in choices], pref.min_batting_options, 11)
    for kind, minimum in (("pace", pref.min_pace), ("spin", pref.min_spin)):
        if minimum:
            add([int(bowling_family(pool[i]) == kind) for i, j, u, c in choices], minimum, 11)
    if pref.budget is not None:
        add([pool[i]["credit"] for i, j, u, c in choices], 0, pref.budget)
    if pref.max_from_team is not None:
        for team_ in sorted({r["teams"][0] for r in pool}):
            add([int(pool[i]["teams"][0] == team_) for i, j, u, c in choices], 0, pref.max_from_team)
    A, lo, hi = np.array(matrix, float), np.array(lower, float), np.array(upper, float)
    values = np.array([u for i, j, u, c in choices])
    solution = milp(-values, integrality=np.ones(len(choices)), bounds=Bounds(0, 1), constraints=LinearConstraint(A, lo, hi), options={"time_limit": 15, "mip_rel_gap": 0.0})
    if not solution.success:
        return {**base, "reason": "No proven optimum was returned for these constraints. No invalid or approximate XI is substituted.", "solver_status": int(solution.status), "solver_message": solution.message}
    x = np.rint(solution.x).astype(int)
    if np.any((x < 0) | (x > 1)) or np.any(A @ x < lo - 1e-6) or np.any(A @ x > hi + 1e-6):
        raise RuntimeError("Selection failed post-solve constraint verification")
    selected = [{**pool[i], "slot": slots[s], "order": s + 1, "utility": value, "contributions": parts}
                for (i, s, value, parts), chosen in zip(choices, x) if chosen]
    selected.sort(key=lambda r: r["order"])
    if len(selected) != 11 or len({r["id"] for r in selected}) != 11:
        raise RuntimeError("XI size or uniqueness validation failed")
    warnings = base["warnings"] + ["Optimal only under this heuristic, window and role constraints. This is not an official selection or an objectively best team."]
    if any(r["role_evidence"].startswith("Inferred") for r in selected):
        warnings.append("Some selected roles are inferred. Verify wicketkeeping and bowling capacity before treating this as a playable XI.")
    return {**base, "status": "optimal_under_declared_model", "reason": None, "eleven": selected,
            "objective_value": float(values @ x), "solver_gap": float(solution.mip_gap),
            "bowling_options": sum("bowler" in r["roles"] for r in selected), "batting_options": sum("bat" in r["roles"] for r in selected),
            "total_credit": sum(r["credit"] for r in selected) if all(r["credit"] is not None for r in selected) else None, "warnings": warnings}


def sensitivity(ranking, preferences=None):
    base = preferences or Preferences(min_bowling_options=4 if ranking.get("scope", {}).get("format") == "Test" else 5)
    scenarios, counts = [], {}
    for experience in (0, 10, 25, 40):
        pref = Preferences(**{**asdict(base), "experience": experience, "performance": 100 - experience, "leadership": 0})
        result = select_eleven(ranking, pref)
        for player in result["eleven"]:
            counts[player["id"]] = counts.get(player["id"], 0) + 1
        scenarios.append({"experience_weight": experience, "status": result["status"], "selected": [p["id"] for p in result["eleven"]]})
    return {"scenarios": scenarios, "selection_count": counts, "interpretation": "Frequency across four preference choices, not a confidence probability."}


def why_not(ranking, player_id, preferences=None, *, locked=None, excluded=None):
    base = select_eleven(ranking, preferences, locked=locked, excluded=excluded)
    alternate = select_eleven(ranking, preferences, locked=sorted(set(locked or []) | {player_id}), excluded=sorted(set(excluded or []) - {player_id}))
    if not base["eleven"] or not alternate["eleven"]:
        return {"base": base["status"], "alternative": alternate["status"], "reason": alternate.get("reason")}
    baseline_ids = {r["id"] for r in base["eleven"]}
    alternate_ids = {r["id"] for r in alternate["eleven"]}
    return {"status": "compared", "objective_cost": base["objective_value"] - alternate["objective_value"],
            "entered": sorted(alternate_ids - baseline_ids), "left": sorted(baseline_ids - alternate_ids),
            "meaning": "Utility lost when this candidate is required, reoptimising every slot. It is not a predicted loss in runs or wins."}
