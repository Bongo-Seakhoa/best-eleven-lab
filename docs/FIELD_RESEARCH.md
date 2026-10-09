# Field placements: a research boundary, not a missing graphic

## The question to estimate

For a known batter–bowler pairing, match state and legal field, estimate the change in the defending side’s expected outcome when the field changes. Moving a fielder can increase one dismissal opportunity while opening another scoring route. A map of catches is therefore not an objective function for field selection.

A useful initial research target is:

```text
field_value(F | context) = expected_runs_conceded(F | context)
                          - context_specific_wicket_value × wicket_probability(F | context)
```

This is a proposed objective, not an implemented or fitted model. In Test cricket, survival, draw probability and the remaining innings structure complicate any fixed wicket value. In limited overs, required rate, wickets in hand and balls remaining matter. A future policy should ultimately be evaluated on a calibrated match-state value, not a universal “one wicket equals N runs” constant.

## Four different biases

**Outcome-selected capture:** keeping catches but not failed chances, boundaries, singles and dots. Define the complete delivery universe independently and require a capture-status row for every delivery, including missing observations.

**Exposure and survivorship:** studying only successful or still-selected players, or only bowlers who dismissed the batter. Retain historical players, zero-wicket matchups, not-outs and unsuccessful spells. A fixture-level denominator is still required to determine what the source never observed.

**Confounding by tactical choice:** captains select fields, bowlers select deliveries and batters respond to perceived opportunities. A short ball with deep protection is not exchangeable with a full ball to an attacking cordon merely because the batter is the same.

**Feedback and policy change:** a new field may change the next shot or delivery. A static replay that moves dots around without modelling those responses can recommend a field that would never produce the assumed shots.

The current application addresses parts of exposure accounting. It does not claim that this resolves the other biases.

## Data needed before modelling

Use the existing match/innings/ordinal identity to join a licensed or independently collected tracking feed. Capture all eleven pre-delivery field positions, distinguishing bowler and keeper, in a documented coordinate frame with venue geometry and batter handedness. Retain delivery line, length, measured speed, bowler style, shot direction and trajectory, ground/air status, interceptions, catches, dropped chances, fumbles, overthrow runs and final scoring outcome. Record fielding opportunities and visibility rather than converting every dot into “runs saved”.

Maintain pre-delivery match state, target, wickets, phase, ball age where known, venue, weather/pitch observations and player identities. Preserve missingness and annotation confidence separately from physical outcomes. A commentator’s positional word is an uncertain text annotation, not a measured coordinate. Archive the unparsed evidence and licensing terms for auditing.

The `assess_spatial_evidence` function only checks a minimal shell: required field names, uniqueness, capture flags, the count of fielders and agreement with an externally supplied ball universe. It does not validate coordinates, trajectories, legal fielding restrictions or causal identifiability. Even its `research_inputs_present` result returns **no recommendations**.

## Modelling sequence

First fit descriptive conditional models on observed deliveries. Use match-grouped, chronological splits and retain a true future holdout. Assess calibration, prediction error and missingness by venue, opponent, batter/bowler handedness and data provider. Separate the wicket component from scoring and retain the joint dependence where it matters.

Then determine whether the observational data identify a useful comparison at all. There must be comparable situations in which more than one candidate field was used. Field legality must be validated against the relevant format, competition and rule version. Recommendations should stay within supported regions rather than extrapolating confidently to novel field formations.

Propensity weighting or doubly robust estimation is a possible research path only with a justified adjustment set, sufficient overlap and reliable action-probability estimation. An unknown human captain’s policy cannot be treated as a known random logging policy. No estimator cures missing confounders by name alone. Where support is poor, output “not identifiable from these data” or a bounded sensitivity analysis rather than an optimum.

A prospective or carefully randomized tactical evaluation would provide stronger evidence than retrospective association. Human cricket expertise and operational constraints belong in that design. Player-level claims should account for multiple searches and unstable small samples.

## Proposed future profile output

A defensible report would say: in the specified context and supported comparison set, field B is estimated to alter scoring and wicket probability by stated amounts, with intervals, exposure counts, overlap diagnostics and legal constraints. It would show the opportunity cost of the gap it opens. It would not simply display the most common successful catch position as the “best” field.

**Current release output:** unavailable spatial evidence; no field recommendation. This is intentional.
