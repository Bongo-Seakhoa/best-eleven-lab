"""Build the original notebook using notebook-aware tooling. No external data needed."""
from pathlib import Path
import nbformat as nbf
ROOT=Path(__file__).resolve().parents[1]
nb=nbf.v4.new_notebook()
md=nbf.v4.new_markdown_cell
code=nbf.v4.new_code_cell
nb.cells=[
md('''# Best Eleven: selection, exposure and uncertainty
## tl;dr
This is a **synthetic, reproducible demonstration**, not a finding about any real cricketer. It executes the same ingestion, ranking, optimization and profile functions as the application. The displayed counts and comparisons are computed below, not manually supplied.

The questions are whether the pipeline produces an auditable eleven, how declared preferences affect that decision, and why exposure belongs beside matchup outcomes. A separate chronological predictive diagnostic illustrates a validation path; it does not establish that the XI is best.'''),
md('''## Context & Methods
### Key assumptions
Use one fictional national team in Test cricket as the principal selection scope. The generator also creates ODI and T20 records, always separated by format and provenance. All dates and model preferences are explicit. The peer baselines, pseudo-counts, role template and score formulas are specified in `docs/METHODOLOGY.md`.

This notebook uses no network, no warehouse credentials and no real-player data. The source contract for future ingestion is [Cricsheet JSON](https://cricsheet.org/format/json). The source does not provide the spatial observations needed for optimal-field advice.'''),
code('''from pathlib import Path
from dataclasses import replace
import sys, tempfile
import pandas as pd
import matplotlib.pyplot as plt
from IPython.display import display, Markdown
root = next(p for p in [Path.cwd(), *Path.cwd().parents] if (p / "src/best_eleven").is_dir())
sys.path.insert(0, str(root / "src"))
from best_eleven.store import connect
from best_eleven.demo import make_demo
from best_eleven.analytics import Scope, rankings, player_profile, coverage
from best_eleven.selection import Preferences, select_eleven, sensitivity
from best_eleven.evaluate import rolling_evaluate
workspace = tempfile.TemporaryDirectory(prefix="best-eleven-notebook-")
db = connect(Path(workspace.name) / "synthetic.sqlite")
scope = Scope(format="Test", team="Cedar XI (demo)", dataset="demo", as_of="2026-10-09")
preferences = Preferences(performance=85, experience=15, min_bowling_options=4)
plt.rcParams.update({"figure.figsize": (9, 5), "font.size": 11, "axes.spines.top": False, "axes.spines.right": False})'''),
md('''## Data
### 1. Generate and ingest the fictional observations
Every generated match passes through the same parser, arithmetic checks and revision-aware storage as an imported archive. The second run checks idempotency. This is functional evidence for the program, not a test of source completeness.'''),
code('''generation = make_demo(db)
repeated = make_demo(db)
assert generation["inserted"] == 108
assert repeated["unchanged"] == 108
c = coverage(db)
assert sum(g["matches"] for g in c["groups"]) == 108
assert all(g["is_synthetic"] == 1 for g in c["groups"])
display(pd.DataFrame(c["groups"])[["format", "matches", "first_date", "last_date"]])
display(Markdown(f"**Computed demonstration size:** {c['deliveries']:,} delivery records and {c['players']} fictional roster identities. Re-ingesting the same generator leaves 108 matches unchanged."))'''),
md('''## Results
### 2. Solve the declared selection problem
The integer model selects distinct players into role-compatible slots. The score is a decision-rule utility, not runs, a percentile or a win probability. Role assignments are not an optimized batting order.'''),
code('''ranking = rankings(db, scope)
selection = select_eleven(ranking, preferences)
assert selection["status"] == "optimal_under_declared_model"
assert len({p["id"] for p in selection["eleven"]}) == 11
assert selection["bowling_options"] >= 4
assert selection["batting_options"] >= 6
xi = pd.DataFrame(selection["eleven"])
display(xi[["order", "name", "slot", "matches", "runs", "average", "wickets", "economy", "utility"]].round(2))
display(Markdown(f"The declared policy selected **{len(xi)} distinct players** from **{len(ranking['players'])} candidates**, using {ranking['matches']} observed team matches. It retained {selection['bowling_options']} bowling and {selection['batting_options']} batting options."))'''),
md('''### 3. Inspect both contribution dimensions
The two discipline scores are separate, peer-normalized heuristics. A tail-order batting score is relative to that role’s baseline, not a claim that the bowler equals a specialist batter. A displayed zero denotes insufficient discipline evidence; it is not measured poor performance.'''),
code('''players = pd.DataFrame(ranking["players"])
chosen = set(xi.id)
fig, ax = plt.subplots()
for selected, label, marker in [(False, "Other candidate", "x"), (True, "Selected", "o")]:
    subset = players[players.id.isin(chosen) == selected]
    ax.scatter(subset.batting_score, subset.bowling_score, s=65, marker=marker, label=label)
ax.set(xlabel="Batting score (role/era-relative heuristic)", ylabel="Bowling score (era-relative heuristic)",
       title="Two contribution measures, one constrained team | synthetic Test data", xlim=(0,100), ylim=(-3,100))
ax.legend(frameon=False)
fig.tight_layout()
plt.show()'''),
md('''### 4. Change preferences without changing the data
Four scenarios allocate 0%, 10%, 25% and 40% to experience, with performance receiving the complement. Leadership is held at zero. This asks how stable the recommendation is under those specific preferences, not how likely a player is to belong in a true best XI.'''),
code('''study = sensitivity(ranking, preferences)
frequencies = players[["id", "name"]].copy()
frequencies["scenarios_selected"] = frequencies.id.map(study["selection_count"]).fillna(0).astype(int)
frequencies = frequencies.sort_values(["scenarios_selected", "name"])
fig, ax = plt.subplots(figsize=(9,6))
ax.barh(frequencies.name, frequencies.scenarios_selected)
ax.set(xlabel="Selections across four declared preference scenarios (not a probability)",
       title="Who remains selected when experience receives more weight? | synthetic", xlim=(0,4.3))
ax.set_xticks([0,1,2,3,4]); fig.tight_layout(); plt.show()
stable = int((frequencies.scenarios_selected == 4).sum())
display(Markdown(f"**{stable} fictional players** remain selected in all four scenarios. Others change or remain outside the team. This result describes only the declared scenarios and this generator."))'''),
md('''### 5. Keep bowlers who did not take the wicket
The player below is a fictional opener. Individual-bowler profiles retain all deliveries, including zero-dismissal matchups. Match-cluster intervals and sample flags are available in the profile export. These associations do not establish causal weakness.'''),
code('''opener = next(p for p in selection["eleven"] if p["slot"] == "opener")
profile = player_profile(db, scope, opener["id"], ranking)
matchups = pd.DataFrame(profile["batting"]["matchups"])
display(matchups[["label", "deliveries", "matches", "dismissals_to_bowler", "wickets_per_100_deliveries", "strike_rate", "evidence"]].head(10).round(2))
assert len(matchups) > 0
assert (matchups.dismissals_to_bowler == 0).any()
fig, ax = plt.subplots(figsize=(9,5))
for has_wicket, label, marker in [(False, "No dismissal observed", "x"), (True, "Dismissal observed", "o")]:
    subset = matchups[(matchups.dismissals_to_bowler > 0) == has_wicket]
    ax.scatter(subset.deliveries, subset.wickets_per_100_deliveries, s=70, marker=marker, label=label)
ax.set(xlabel="All recorded matchup deliveries", ylabel="Credited striker dismissals per 100 deliveries",
       title=f"Exposure remains visible: {opener['name']} | synthetic Test data")
ax.legend(frameon=False); fig.tight_layout(); plt.show()
display(Markdown(f"The profile retains **{int((matchups.dismissals_to_bowler == 0).sum())} zero-dismissal matchups**. Excluding them would change the evidence base before any model was fitted."))'''),
md('''### 6. Demonstrate a chronological validation path
This is a **different, simple predictive model** of batter outcomes, not the XI utility model. Each fold uses completed prior matches to predict runs and dismissal probability in a later period. It compares against a pooled past-only baseline. A lower error in fictional data does not establish a cricket advantage.'''),
code('''diagnostic = rolling_evaluate(db, replace(scope, team=""))
folds = pd.DataFrame(diagnostic["folds"])
assert len(folds) == 3
assert all(folds.train_end_exclusive < folds.test_end_exclusive)
display(folds[["train_end_exclusive", "test_matches", "runs_rmse", "baseline_runs_rmse", "wicket_brier", "baseline_wicket_brier"]].round(4))
fig, ax = plt.subplots()
x = range(1, len(folds)+1)
ax.plot(x, folds.runs_rmse, marker="o", label="Past-only batter shrinkage")
ax.plot(x, folds.baseline_runs_rmse, marker="s", linestyle="--", label="Pooled past-only baseline")
ax.set(xlabel="Chronological holdout fold", ylabel="Runs per non-wide delivery: RMSE",
       title="Predictive baseline check, not XI validation | synthetic Test data")
ax.set_xticks(list(x)); ax.legend(frameon=False); fig.tight_layout(); plt.show()'''),
md('''### 7. Verify the spatial guard
Even accurate catcher identities cannot supply pre-delivery field layouts, unobserved missed chances or the runs conceded through gaps. The project does not produce a false wagon wheel or field recommendation from these records.'''),
code('''assert profile["spatial"]["status"] == "unavailable"
assert profile["spatial"]["recommendations"] == []
display(Markdown("**Spatial result:** " + profile["spatial"]["reason"]))'''),
md('''## Takeaways
The executed cells establish repeatable ingestion, a valid eleven under declared constraints, interpretable preference sensitivity and full matchup exposure accounting for the fictional dataset. They also demonstrate an out-of-time predictive diagnostic and a fail-closed spatial boundary.

They do **not** establish that the scoring policy is calibrated on real cricket, that the source is complete, that a particular real player is underrated, or that an unplayed XI would have won. The next milestone is a reconciled national dataset and an independently reviewed application of `docs/research/BAVUMA_PROTOCOL.md`.

The notebook intentionally reuses production functions rather than maintaining a second implementation of the scoring rules.'''),
code('''db.close()
workspace.cleanup()
print("Executed all checks on explicitly synthetic data; temporary database removed.")''')]
nb.metadata={'kernelspec':{'display_name':'Python 3','language':'python','name':'python3'},'language_info':{'name':'python'}}
nbf.validate(nb)
nbf.write(nb,ROOT/'notebooks/01_selection_and_matchups.ipynb')
