"""Past-only predictive diagnostics. Never claim results for teams that did not play."""
from dataclasses import asdict
import numpy as np
import pandas as pd


def rolling_evaluate(db, scope, folds=3, prior_balls=120):
    if not 1 <= folds <= 10 or prior_balls <= 0:
        raise ValueError("Invalid fold count or shrinkage strength")
    where, args = scope.where()
    if scope.team:
        where += " AND i.batting_team=?"
        args += [scope.team]
    f = pd.read_sql_query(f"""SELECT d.match_id,d.batter,m.start_date,m.end_date,SUM(d.bat_runs) AS runs,
        SUM(d.bat_runs*d.bat_runs) AS runs_squared,SUM(d.striker_wickets) AS wickets,COUNT(*) AS opportunities
        FROM deliveries d JOIN matches m ON m.id=d.match_id JOIN innings i ON i.match_id=d.match_id AND i.number=d.innings
        WHERE {where} AND i.super_over=0 AND d.faced_ball=1 GROUP BY d.match_id,d.batter""", db, params=args)
    if f.empty or f.match_id.nunique() < 20:
        return {"status": "insufficient_data", "folds": [], "reason": "This diagnostic needs at least 20 completed matches."}
    dates = sorted(f.start_date.unique())
    cuts = sorted(set(dates[int((.5 + .5 * i / folds) * (len(dates) - 1))] for i in range(folds)))
    output = []
    for i, cut in enumerate(cuts):
        end = cuts[i + 1] if i + 1 < len(cuts) else scope.as_of
        train = f[f.end_date < cut]
        test = f[(f.start_date >= cut) & (f.start_date < end)]
        if train.empty or test.empty:
            continue
        totals = train[["runs", "wickets", "opportunities"]].sum()
        base_r, base_p = totals.runs / totals.opportunities, totals.wickets / totals.opportunities
        g = train.groupby("batter")[["runs", "wickets", "opportunities"]].sum()
        g["pred_runs"] = (g.runs + prior_balls * base_r) / (g.opportunities + prior_balls)
        g["pred_wicket"] = (g.wickets + prior_balls * base_p) / (g.opportunities + prior_balls)
        t = test.join(g[["pred_runs", "pred_wicket"]], on="batter")
        t["pred_runs"], t["pred_wicket"] = t.pred_runs.fillna(base_r), t.pred_wicket.fillna(base_p)
        n = t.opportunities.sum()
        mse = (t.runs_squared - 2 * t.pred_runs * t.runs + t.opportunities * t.pred_runs ** 2).sum() / n
        mse0 = (t.runs_squared - 2 * base_r * t.runs + t.opportunities * base_r ** 2).sum() / n
        brier = (t.wickets * (1 - t.pred_wicket) ** 2 + (t.opportunities - t.wickets) * t.pred_wicket ** 2).sum() / n
        brier0 = (t.wickets * (1 - base_p) ** 2 + (t.opportunities - t.wickets) * base_p ** 2).sum() / n
        output.append({"train_end_exclusive": cut, "test_end_exclusive": end, "train_matches": int(train.match_id.nunique()),
            "test_matches": int(test.match_id.nunique()), "test_opportunities": int(n), "runs_rmse": float(np.sqrt(mse)),
            "baseline_runs_rmse": float(np.sqrt(mse0)), "wicket_brier": float(brier), "baseline_wicket_brier": float(brier0),
            "observed_wicket_rate": float(t.wickets.sum() / n), "predicted_wicket_rate": float((t.pred_wicket * t.opportunities).sum() / n)})
    return {"status": "evaluated" if output else "insufficient_data", "scope": asdict(scope), "folds": output,
        "target": "Batter runs and bowler-credited striker dismissal per non-wide delivery",
        "model": "Past-only per-batter shrinkage compared with a pooled past-only baseline. This is a diagnostic baseline, not the XI utility model.",
        "limits": ["Training uses only matches whose final recorded day precedes the cutoff. No match crosses the training boundary.",
                   "These diagnostics do not validate the XI heuristic or measure whether an unplayed XI would win.",
                   "No tuning on holdout folds; use nested temporal validation before optimising model settings.",
                   "Unseen players receive the pooled prior; future career totals are never used."]}
