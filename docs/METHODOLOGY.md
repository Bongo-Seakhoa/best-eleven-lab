# Methodology and model card

**Release:** 0.1 research prototype. **Evidence in the distributed preview:** fictional, seed 42. **Claim:** a runnable, auditable decision rule. **Not claimed:** a validated best team, a causal weakness, a complete career, or a probability of winning.

## 1. Population and time

A scope fixes format, gender, team level, optional competition, candidate team, evidence start, exclusive as-of date and real versus synthetic provenance. Formats are never pooled. Matches must start on or after the start date and finish strictly before the as-of date. This avoids using the final innings of a Test that had not finished at the decision cutoff.

Team filtering restricts both candidate identities and their reported team-specific performances. Peer comparisons can use all teams in the remaining scope. Loading only one country’s archive limits the peer population to that country and its opponents in those matches; fetch the wider format archive before interpreting the result internationally.

Source roster membership is an appearance record, not automatic proof of a starting-XI slot, eligibility, availability or fitness. Supersubs and replacements can be included. The implementation does not infer injuries, citizenship, player availability or squad announcements.

## 2. Accounting

The storage identity is `(match_id, innings_number, ordinal)`. An over/ball decimal is not a unique delivery identity when illegal deliveries or miscounted overs occur.

Batter runs exclude extras. Balls faced exclude wides; the implementation counts non-wide no-balls as faced balls. Legal bowling balls exclude wides and no-balls. Bowler runs conceded are batter runs plus wides plus no-ball extras, excluding byes, leg-byes and penalty extras. Rate denominators always name which of these units is used.

Batting average = total batter runs / actual dismissals. A zero-dismissal denominator produces null, not a fabricated finite average. Run-outs count against the player actually dismissed, including a non-striker. Retired hurt and retired not out do not count as dismissals. Bowler credit includes bowled, caught, caught-and-bowled, lbw, stumped and hit wicket; it excludes run-out and retirement. Multiple wicket events on one delivery remain separate. A four or six completed by running is not counted as a boundary when the source flags `non_boundary`.

Super-over deliveries are preserved but excluded from the normal analysis and fantasy aggregates. Pre- and post-innings penalty runs are stored separately. `info.missing` is retained as source metadata; a missing umpire, review or award does not cause valid deliveries to be discarded. Broader source completeness still needs an independent fixture/scorecard reconciliation.

## 3. Recency and peer baselines

Each match observation has weight `w = 2^(-age_days / half_life_days)`. A half-life of zero assigns equal weights. Dates are measured from the match’s final recorded date.

Batting baselines are grouped by five-year era, competition and observed batting-position band: opening (1–2), middle (3–5), lower middle (6–7), tail (8+). Bowling baselines use era and competition. A player’s own records are removed from their peer baseline. A cell with fewer than 200 peer batting/bowling balls or ten dismissals/wickets falls back to the broader peer pool. The output reports fallback-cell counts.

The expected baseline for a player averages cell baselines using that player’s weighted exposure in each cell. This is a transparent first normalization, not a full causal or hierarchical era adjustment. Fallbacks can dilute era and role matching. Batting position comes from order of first observation, not a separately verified batting-order feed. Verify edge cases before using historical role claims.

## 4. Performance scores

Let `R`, `B`, `O` be recency-weighted batter runs, balls faced and dismissals. Let `r0` and `a0` be the player’s peer scoring-rate and batting-average baselines.

```text
rate_index    = ((R + k × r0) / (B + k)) / r0
average_index = ((R + 5 × a0) / (O + 5)) / a0
```

The ball pseudo-count `k` is 360 for Test, 240 for ODI and 120 for T20. These are declared heuristic regularization strengths, not fitted optimal values.

For any positive relative index `x`:

```text
S(x) = clip(50 + 30 × tanh(log(max(x, 0.001)) / 0.65), 0, 100)
```

The bounded transform centers parity on 50 and limits the influence of extremes. Positive finite indices approach scores of 20 and 80, so this is not a percentile rank. Batting score blends `S(rate_index)` and `S(average_index)` with scoring-rate weights of 0.20 (Test), 0.45 (ODI) and 0.65 (T20).

For bowling, the model regularizes runs conceded per legal ball and credited wickets per legal ball with the same format-specific `k`. Economy index is the peer concession rate divided by the regularized player concession rate. Wicket index is the regularized player wicket rate divided by the peer wicket rate. The wicket component has weight 0.75 in Test and 0.55 in ODI/T20; the remaining weight is economy.

Raw statistics remain visible beside the scores. The indices are associations in observed matches; opposition quality, venue, pitch, match situation, ball age, home advantage and selection effects are not fully adjusted. A bowler’s batting score can look high relative to tail-order peers without implying specialist-batter quality. Roles therefore constrain slot eligibility. A score of zero internally denotes insufficient discipline evidence, and cannot fill a slot that needs that evidence; it is not a measured percentile of zero.

## 5. Experience, appointments and uncertainty

```text
experience = min(100, 100 × log(1 + observed_matches) / log(151))
leadership = min(100, 100 × log(1 + captain_matches + 0.5 × vice_captain_matches) / log(101))
effective_matches = (sum(w))² / sum(w²)
```

Experience is explicitly exposure within the selected, available-record window, not complete lifetime experience. A limited source window can understate a long career. That limitation is not corrected by the logarithm. Leadership represents documented appointments, not effectiveness, tactical ability, psychological attributes or intrinsic value. Both appointment counts must be known for every eligible candidate before a nonzero leadership preference is allowed.

Metadata is scoped to format and team level and must have been observed before the as-of date, with a valid effective date. Most recent applicable rows replace older snapshots. The user must resolve conflicting sources: automatic source reliability adjudication and field-by-field merging are not implemented.

An optional sampling penalty is `caution × 15 / sqrt(1 + effective_matches / 10)`. It is a policy preference for more evidence, not a statistical confidence bound. Sampling already influences regularization, and experience overlaps with exposure; weighting all three strongly can reward longevity more than intended. Inspect sensitivity instead of assuming independent information.

Profile intervals use 250 deterministic bootstrap resamples of whole matches. Fewer than three match clusters yields no interval. Undefined denominators are recorded; if too many resamples have zero denominator, the upper endpoint is not supplied. Percentile intervals are exploratory, not simultaneous or family-wise guarantees. Serial dependence between matches, scheduling, source missingness and multiple comparisons remain material limitations.

## 6. Team optimization

The fixed template is two opener slots, three batter slots, one wicketkeeper, one flexible slot and four bowler slots. The opener count can be lowered, replacing opener slots with ordinary batter slots. Capability constraints additionally require six batting options and four bowling options in Test or five in limited overs by default. Pace/spin requirements, source-verified roles, dated availability, a budget and a maximum per team are optional.

Usage-based role inference needs minimum observed exposure. Batting eligibility uses at least 120/90/45 balls in Test/ODI/T20 and median position no worse than seven. Bowling eligibility uses 240/120/60 legal balls. An opener needs at least 35% of observed innings at positions one or two. Stumping evidence can identify a keeper, but a reviewed role record is preferable. Sourced role snapshots override inference; a role alone cannot create performance evidence.

For a player in a slot, quality is batting score for opener/batter/keeper, bowling score for bowler, and the stronger eligible discipline for the flexible slot. This is not an additive run-value model of all-round contribution; the current flexible slot can be a specialist when other capability requirements are met. Such a heuristic can undervalue moderate all-rounders relative to specialists. No claim of fully estimated team synergy is made.

```text
utility = (performance_weight × slot_quality
           + experience_weight × experience
           + leadership_weight × leadership) / total_weight
          - sampling_penalty
```

Binary assignment variables must fill every slot once and use every player at most once. Locks require inclusion; exclusions remove candidates. SciPy’s MILP interface solves the linear objective under those constraints. The result is accepted only when the solver reports optimality and a separate check verifies integrality, all constraints and eleven distinct identities. A timeout or infeasibility does not return a purportedly valid XI. The slot order is not a learned optimal batting order.

“Why not?” compares the current solution with one requiring the chosen candidate. Existing locks persist; the candidate’s own exclusion is removed for the alternative. The difference is utility, not runs or win probability. Four sensitivity scenarios vary the experience weight between 0, 10, 25 and 40 while setting performance to the complement and leadership to zero. Frequency across these scenarios is not a selection probability.

## 7. Player profiles and archetypes

The full exposure table contains all recorded matchup deliveries, not just wickets. It reports balls faced, legal balls, all deliveries, runs, conceded runs, credited striker dismissals and distinct matches. Wicket rate in these tables is credited striker dismissals per 100 deliveries. The separate dismissal-type distribution is conditioned on actual dismissals and must not be treated as a matchup-risk estimator.

Profiles include opponent, individual matchup, over band, season and venue cuts. Bowling-style and batting-hand cuts need source-attributed metadata; unknown is its own group. Applicable metadata at the analysis cutoff labels the historical deliveries; this is not a reconstructed delivery-date style history, so changing styles require additional temporal enrichment. The implemented batter archetypes in bowling profiles are observed batting-order bands. They are not stroke-technique, aggression, handedness or body-type inferences. Over bands are not necessarily official powerplays; Test over number is not ball age.

At least 60 deliveries and five matches are required to remove the sparse-evidence warning. That is a display rule, not proof of statistical significance. There is no automatic “weakest against” claim after searching many groups. Spatial advice is always unavailable with the standard input.

## 8. Predictive diagnostic and fantasy

The separate rolling diagnostic fits past-only regularized batter runs per non-wide delivery and credited-dismissal probability. It evaluates run RMSE and wicket Brier score against a pooled past-only model over chronological folds. A Test cannot cross a training boundary. Unknown batters use the pooled prior. This diagnostic does **not** validate the XI utility model or the outcomes of unplayed teams. Hyperparameters are not tuned on its holdouts.

Fantasy uses explicit research point weights and a historical mean per roster appearance, including zero-contribution appearances. It is a baseline projection, not a calibrated next-match forecast. Fantasy captain multipliers are distinct from leadership metadata. The CLI selects an XI on base expected points and then allocates multipliers; it does not jointly optimize captain multipliers and XI membership under a platform’s full rules. Run-out shares, economy/strike-rate bonuses and official credits are not presumed.

## 9. What must be validated on real records

Reconcile selected complete scorecards, including non-striker run-outs, no-balls, penalties, retirements and super overs. Check archive completeness against a fixture universe. Verify name/identity coverage, role sources, metadata dates and historical comparisons. Benchmark the scoring rule against simple baselines out of time, use a separate calibration period and report failed comparisons. Test source revisions and scale on actual full national archives. Obtain independent cross-provider review before calling the project accepted or production-ready.
