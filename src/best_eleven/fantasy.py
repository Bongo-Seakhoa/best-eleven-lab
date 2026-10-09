"""Provider-neutral historical fantasy baseline, with explicit scoring rules."""
from dataclasses import dataclass, asdict
import math
import pandas as pd
from .analytics import evidence_frames

@dataclass(frozen=True)
class FantasyRules:
    name: str = "Research scoring, not an official platform"
    run: float = 1
    four_bonus: float = 1
    six_bonus: float = 2
    wicket: float = 25
    catch: float = 8
    stumping: float = 12
    captain_multiplier: float = 2
    vice_captain_multiplier: float = 1.5

    def __post_init__(self):
        for k, value in asdict(self).items():
            if k != "name" and (not math.isfinite(value) or value < 0):
                raise ValueError("Fantasy coefficients must be finite and non-negative")


def fantasy_projection(db, scope, rules=None):
    rules = rules or FantasyRules()
    bat, bowl, appearances = evidence_frames(db, scope)
    if scope.team:
        appearances = appearances[appearances.team == scope.team]
    if appearances.empty:
        return {"rules": asdict(rules), "players": []}
    base = appearances.drop_duplicates(["match_id", "player_id"])[["match_id", "player_id"]].copy()
    for frame, name in ((bat, "bat"), (bowl, "bowl")):
        if len(frame):
            frame = frame.copy()
            frame["points"] = rules.run * frame.runs + rules.four_bonus * frame.fours + rules.six_bonus * frame.sixes if name == "bat" else rules.wicket * frame.wickets
            base = base.merge(frame.groupby(["match_id", "player_id"]).points.sum().rename(name), on=["match_id", "player_id"], how="left")
        else:
            base[name] = 0.0
    where, args = scope.where()
    field = pd.read_sql_query(f"""SELECT f.match_id,f.player_id,f.kind FROM fielding f JOIN matches m ON m.id=f.match_id
        JOIN innings i ON i.match_id=f.match_id AND i.number=f.innings WHERE {where} AND i.super_over=0""", db, params=args)
    if len(field):
        field["points"] = field.kind.map({"caught": rules.catch, "caught and bowled": rules.catch, "stumped": rules.stumping}).fillna(0)
        base = base.merge(field.groupby(["match_id", "player_id"]).points.sum().rename("field"), on=["match_id", "player_id"], how="left")
    else:
        base["field"] = 0.0
    base["points"] = base[["bat", "bowl", "field"]].fillna(0).sum(axis=1)
    vals = base.groupby("player_id").points.agg(["mean", "std", "count"]).reset_index().rename(columns={"mean": "expected_points", "std": "sample_sd", "count": "appearances"})
    return {"rules": asdict(rules), "players": vals.astype(object).where(pd.notna(vals), None).to_dict("records"),
        "warnings": ["Historical mean per roster appearance is a baseline, not a calibrated next-match forecast.",
                     "Did-not-bat and did-not-bowl appearances remain with zero points. Replacements can be present in rosters.",
                     "Official platform role rules, run-out allocation, bonuses, credits and current squads must be supplied, not guessed.",
                     "Fantasy captain multipliers are not real-world leadership appointments."]}


def fantasy_captains(selected, values, rules):
    if len(selected) < 2:
        return {"captain": None, "vice_captain": None}
    candidates = [((rules.captain_multiplier - 1) * values[c["id"]] + (rules.vice_captain_multiplier - 1) * values[v["id"]], c["id"], v["id"])
                  for c in selected for v in selected if c["id"] != v["id"]]
    bonus, captain, vice = max(candidates)
    return {"captain": captain, "vice_captain": vice, "extra_expected_points": bonus}
