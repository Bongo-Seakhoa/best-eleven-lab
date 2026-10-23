# Methodology

How Best Eleven turns 11.7 million deliveries into a rating, a profile and an eleven. Numbers quoted here come from the October 2026 build; each build recomputes them.

## 1. Data

**Matches.** Cricsheet's `all_json.zip` (schema 1.2 and 1.3) is ingested into a Parquet warehouse in one streaming pass. Each match is validated as a unit:

- runs and extras must reconcile
- a ball can't be both wide and no-ball
- every person must be registered
- batters must belong to the batting side

A failing match is quarantined with its reason rather than partly stored; the October build quarantined none. Five-ball overs (The Hundred) are supported. Super-over deliveries are kept but excluded from every rating.

**Scopes.** Each match is assigned to one scope:

- the six international formats: men's and women's Tests, ODIs and T20Is
- one scope per mapped league ([config/competitions.json](../config/competitions.json))
- `other` for everything else, which is stored but not rated

**Player database.** Wikipedia and Wikidata fill what match data cannot:

- batting hand, bowling style, role and date of birth
- full career totals
- current national and franchise squads, with C/VC markers per format
- reported retirements and come-backs
- formal captaincy records
- complete historic career lists for every national side

Identity runs from a Wikipedia title to a Wikidata item, then to an ESPNcricinfo id and Cricsheet's people register. Name matching is a fallback, accepted only within the team's own player pool. Every reference row keeps its source page and revision id.

## 2. Valuing a ball

**Limited overs.** `RE(u, w)` is the expected number of further runs with `u` legal balls left and `w` wickets down. It is fitted from complete, full-length, non-D/L first innings with the Duckworth–Lewis form `Z0(w)·(1 − e^(−b(w)·u))`, separately for each wickets-lost level and era block (T20: to 2012, 2013–18, 2019–22, 2023+; ODI: to 2010, 2011–18, 2019+). It is then made monotone in wickets. Weighted RMSE against the raw cell means is 0.8 runs for men's T20 and 2.3 for ODIs.

A ball's *contest value* to the batting side is:

    batter runs + [RE(after the ball) − RE(before)]

The change in RE splits into the cost of using a legal ball and the cost of any wicket. The striker is charged for their own dismissal (including run-outs); a non-striker's run-out is charged to them separately. Wides and no-ball runs belong to the bowler alone. Byes and leg-byes cost the batter the ball but are charged to no one.

**Tests.** There is no balls-remaining clock, so a ball is worth `runs − W(year) × dismissal`. Here `W` is that year's runs per dismissal (28.8 in 2001, 27.9 in 2026), which centres an average batter's ball at zero.

## 3. Removing the opposition and the context

For each international format, and for men's and women's franchise cricket pooled across leagues, a ridge regression fits per-ball contest value on indicators for:

- batter and bowler
- batting side and bowling side
- context: year × phase × innings × home side (with competition added for the leagues)

Penalties are empirical-Bayes: noise variance over between-player variance, estimated separately for batters and bowlers. A penalty of λ is the same as adding λ average balls to each record. Team effects are almost unpenalised. They carry the strength of a whole attack or batting order, which matters when a weak side's individual players are rarely seen elsewhere. Without them, associate batters facing other associates top the T20I lists.

The adjusted value credited to a batter for one ball is:

    observed value − (bowler effect + bowling-side effect + context effect)

Bowlers are treated the same way. Sums of these values are additive, so any window or team filter is a sum of season rows. Values are centred on an average Full-Member player facing Full-Member opposition.

The home side of a venue is the team that plays most often at that city (40% minimum share). Designated home grounds abroad therefore count as home, and neutral venues stay neutral.

| Fit group | Matches | Deliveries | Selection λ (batters) | λ (bowlers) |
|---|---:|---:|---:|---:|
| Men's Tests | 895 | 1,722,675 | 635 | 1,104 |
| Men's ODIs | 2,589 | 1,373,116 | 594 | 1,199 |
| Men's T20Is | 3,592 | 809,101 | 182 | 289 |
| Women's ODIs | 614 | 321,871 | 248 | 970 |
| Women's T20Is | 2,183 | 496,351 | 109 | 166 |
| Men's franchise T20 | 6,804 | 1,570,992 | 618 | 660 |
| Women's franchise T20 | 828 | 183,603 | 405 | 557 |

Women's Tests (24 matches) are too few to adjust; their values are centred raw contest values.

**Why "selection λ".** Selection compares specialists, so the batting penalty used downstream is estimated among top-seven batters. Estimated over everyone, tail-enders stretch the spread of true ability and the penalty collapses to 119 balls in men's Tests. That once let a batter with 418 runs outrank established Test players.

## 4. Scores

For a window `[from, to]` with optional recency half-life `h` (a season `t` years before the window end gets weight `0.5^(t/h)`), each player gets four components:

| Component | Batting | Bowling |
|---|---|---|
| Quality | Σ adjusted value ÷ (balls + λ); per innings in Tests, per 100 balls otherwise | −Σ adjusted cost ÷ (balls + λ), per 100 balls |
| Legacy | Σ adjusted value over the window | −Σ adjusted cost |
| Experience | Matches in the format up to the window end, plus caps before ball-by-ball coverage (from Wikipedia) | same |
| Leadership | Matches formally captained in that format, plus half a match for a current vice-captaincy | same |

Quality and legacy are standardised against every qualified player of every team in the same window (50 is average, 15 points is one standard deviation), so a team XI and the World XI share one scale. Experience and leadership are log-scaled against the most experienced player and the longest-serving captain.

### Priors for short records

The λ in the quality row pulls a short record towards a prior. In international formats that prior is no longer zero (an average Full-Member player) but what the player's cricket elsewhere predicts: `(Σ value + λ × prior) ÷ (balls + λ)`. [src/best_eleven/model/priors.py](../src/best_eleven/model/priors.py) builds it on every export:

- **Transitions, not exchange rates.** Nothing carries across one to one. For a target format and each source (the other international formats of that gender, and that gender's leagues taken together, one fit and one scale), it fits `target rate = α + β × source rate` by weighted least squares on players with at least 300 balls in both, each weighted by the reliability of his target rate. The source rate is shrunk for its own sample first. In men's cricket a league batting edge carries into T20Is almost whole (β ≈ 1.01) but every batter drops about 0.045 runs a ball; only about three quarters reaches ODIs (β ≈ 0.77); less than half of a T20I edge reaches Tests (β ≈ 0.42). League values already account for each league's strength through the competition term in section 3.
- **The newcomer baseline.** The ball-weighted rate of players in their first season of the format. Debutants are below average, so this is lower than zero.
- **Combining.** A player's prior is the precision-weighted mean of the baseline and his sources' predictions (weight: the source's reliability for him over the transition's residual variance). A thin record elsewhere moves him a little from the baseline; a long one moves him a lot.
- **Checked on debutants.** On every build the transitions are refitted on seasons before 2019 (the shrinkage λ and the adjusted per-ball values themselves come from the whole-archive fit, as in the calibration of section 9, so the check is slightly optimistic) and score everyone who debuted in a format from 2019 on, using only what they had done before their debut, against their first two seasons there. The prior must beat the old zero prior in every format with enough debutants. In the October build it did in all ten, often by a lot (men's T20I batting: weighted squared error 0.197 against 0.329; women's T20I batting 0.303 against 0.812), and it edged the plain newcomer baseline in each. Women's Tests have too few debutants to judge.
- **Limits.** First-class records are not in the ratings, so Test priors lean on white-ball cricket, the weakest links. A prior uses everything a player did elsewhere in the archive, later seasons included, which suits all-time and fantasy questions but means a historical window can know how a career turned out. Leagues keep the zero prior.

## 5. Roles

Roles come from the record within the window. Minimum evidence is sized for a six-year window and scales with the window length (between 0.35× and 2×); the "evidence bar" control multiplies it.

| Role | Rule |
|---|---|
| Opener | qualified batter, at least half of innings at 1–2 |
| Top-order batter | qualified batter, at least 60% of innings at 1–6 |
| Finisher (limited overs) | qualified batter, at least 60% of innings at 4 or lower |
| Wicketkeeper | kept in at least 30% of matches (keeper inferred per match from stumpings and record) |
| All-rounder | batting position 7.5 or higher on average, batting and bowling both at 60% of the bar, enough balls bowled per match |
| Pace / spin bowler | qualified bowler of that family (Wikipedia style, or the classifier) |

Minimum balls at a 6-year window: Tests 500 batting / 900 bowling; ODIs 300 / 450; T20s 150 / 180.

## 6. The eleven

Each player has a utility per eligible slot type:

    utility = Σ weight × component ÷ Σ weights

The quality component depends on the slot:

- batting skill for batting slots
- 85% batting and 15% keeping for the keeper
- an even split of batting and bowling for all-rounders
- bowling skill for bowlers

The selector maximises total utility subject to:

- every slot filled
- each player used once
- locks honoured and exclusions removed
- one optional group cap: either a maximum per country (World XIs) or a maximum number of overseas players (leagues)

With one kind of group cap the problem is a network (source → group → player → slot type → sink), so successive shortest paths on a min-cost flow give the exact optimum. Locks are added as a bonus larger than any possible utility gap. Combining both caps breaks the network structure and is refused rather than approximated. [tests/test_solver_parity.py](../tests/test_solver_parity.py) checks 120 random instances against SciPy's MILP on every run.

If the evidence bar leaves a slot without enough eligible players, it is lowered in steps (60%, 35%, 20%) and the page says so. The captain is the current captain (squad-page marker) with the most captaincy matches; otherwise the most experienced captain in the eleven. The gloves go to whoever in the eleven keeps most often. *Robustness* re-solves 20 times with every weight varied at random by up to ±25% and reports how often each player stays.

**League overseas limits** come from each league's rules, with sources in the config: IPL 4, SA20 4, BBL 3, PSL 4, CPL 4, WPL 5 (one of them from an Associate nation), WBBL 3, The Hundred 3. A player is overseas when their national side, from international appearances or Wikipedia, differs from the host country.

**Availability.** *Current squad* means named in a current national or franchise squad on Wikipedia for that format. Sections older than 15 months and withdrawn players are ignored. *Active* means in a current squad, or played the format in the last 18 months (24 for Tests and leagues), and not reported retired from it. A later appearance overrides a retirement statement.

## 7. All eras

From Wikipedia's national player lists: Tests from 1877, ODIs from 1971, 11,601 career rows in total (including T20Is and women's lists). Careers are assigned to the decade of their midpoint. That decade's batting average (total runs over total dismissals across every list) and bowling average give the era baselines.

- **Batting quality:** `(runs + 8 × era average) ÷ (dismissals + 8) ÷ era average`.
- **Bowling quality:** the era bowling average divided by the player's average, shrunk with 10 (Tests) or 12 (ODIs) pseudo-wickets.
- **Legacy:** runs above the era average and wickets × era bowling average − runs conceded.

The lists carry no batting positions, so openers are not separated from the rest of the top order. World XIs default to Full-Member careers, because era adjustment cannot see opposition strength.

## 8. Profiles

Profiles exist for players with at least 300 balls faced or bowled in Tests (150 in ODIs, 90 in T20s, 75 in The Hundred) in some competition.

**Splits.** Every split counts every ball faced or bowled, never dismissals alone. A batter caught often off one bowling type but scoring heavily against it is not mislabelled weak. Values are adjusted runs per 100 balls against an average player facing the same opponents, with a 95% interval.

A split is flagged a strength or weakness only when it differs from the player's own overall level by more than 1.96 standard errors, with at least 300 / 150 / 90 balls. With several splits per player, about one flag in twenty can be chance, and the site says so.

**Bowling types.** These come from the Wikipedia style, grouped as right-arm pace, left-arm pace, off-spin, leg-spin, left-arm orthodox and left-arm wrist-spin. A gradient-boosted classifier fills the gaps where Wikipedia has nothing. Its features are new-ball and death-over usage, how often the bowler opens, the mix of caught-behind, stumped, bowled and lbw dismissals, and wides and byes. Cross-validated it is 89% accurate (AUC 0.965); only predictions above 0.85 confidence are kept, and those are 94% accurate. Model labels are marked as such everywhere.

**Batter types** (for bowlers' splits) are batting hand, batting-order band, and tempo: strike-rate tercile within the band.

**Field plans** translate rates into a nine-fielder shape. Each rate is shrunk toward peers facing the same bowler family:

- edges caught by the keeper
- other catches
- bowled plus lbw
- stumpings
- fours, sixes, and ones-to-threes

The plan starts from a conventional base for the format, phase and bowler type, within the outfield limits. It then adds a catcher behind when edges run 20% above peers, adds or removes a boundary rider when boundary rates differ by 15%, and so on; each reason is listed with its index. Cricsheet records no shot or catch locations, so the counts come from data while the named positions follow convention, mirrored for left-handers.

## 9. XI vs XI

Each side is a Best XI picked from any international format or league of one gender, in any shape, and both play one match format: a Test, ODI or T20I, or a league match when both sides come from leagues of the same format (one fit, one scale). The default is the Test World XI against the T20I World XI in an ODI.

**Rating a player in the match format.** The player's own numbers come first; nothing is translated while a real record exists. When a side is picked from the match format, its players keep their own window ratings. Otherwise, for batting and for bowling separately:

1. his record in the match format over his side's years, if he did it then: the same rating that format's own Best XI gives him (same team filter, and Full-Member matches only for a World XI);
2. otherwise his whole record in the match format up to the side's last year, if he ever did it;
3. only if he never did it in that format, what his other cricket predicts for it (the prior of section 4, from `model/priors.json` when the format's scope never saw him).

So a batter who bowled no ODI overs in his side's years still bowls on his earlier ODI record, and nothing after a side's last year is used.

In the default matchup most of the 22 sit on step 1. How much a player bowls comes from his usual workload in the match format, or failing that in the format he was picked from. The tale of the tape uses the same order, so both elevens are compared in the match format's own figures.

**Shapes and swaps.** Best XI and XI vs XI share a manual picker. Recommendations retain their evidence and availability filters; the picker also offers players below those thresholds, with warnings. A real, scorable record in the selected team and format is required. Current-window records take precedence; a player with no season rows in the window may use their earlier record through the selected end year, labelled with its actual years. Future season rows are excluded. The reference population stays the selected window's, and the existing priors and static biography flags retain their documented scope.

A preview replaces exactly one player, locks the resulting eleven, and uses the same exact selector for its final role assignment. Roles may rebalance within those eleven. A different role composition or exceeded country/overseas cap is shown before confirmation; accepting the swap stores the revised slots and raises a cap only as far as necessary. Evidence and availability settings stay as chosen. Both old and new elevens are scored on the same reference settings for the utility difference. XI vs XI additionally recomputes the whole proposed side's projected contribution, including its bowling allocation. Clear manual picks reselects under the current presets; Reset composition explicitly restores the default shape.

**From ratings to runs.** A player's rating is adjusted runs per ball from section 4, before it is scaled to 0–100: runs added per ball faced and runs saved per ball bowled, against a Full-Member average and shrunk for short records. A side becomes runs per innings in three steps ([site/assets/js/engine/versus.js](../site/assets/js/engine/versus.js)):

- **Batting.** Each position faces its usual share of an innings. A batter adds `share × balls per innings × batting rate`.
- **Bowling.** The best bowlers bowl first, each up to the format's quota (a fifth of the innings in limited overs, at most 35% in a Test innings) and no more than a quarter above their usual workload. If overs remain, the most-used regular bowlers take more, up to the quota. Overs still uncovered, as in an eleven of batters, go to anyone up to the quota, and an occasional bowler (under 5% of an innings usually) is charged no better than what part-timers really concede in that format: players who average an over a match or less, measured from the archive (in men's ODIs 0.21 runs a ball worse than an average bowler). An occasional bowler's own short record comes from spells chosen to suit him, not from bowling a full share.
- **The match.** Each side scores `par + its batting − the other side's bowling`. The edge is the gap between those scores times the innings each side bats, in runs per match.

**Where the constants come from.** [src/best_eleven/model/versus.py](../src/best_eleven/model/versus.py) measures them from the archive for each gender, format and tier: mean legal balls in a full-length first innings, mean first-innings runs (par), the share of those balls faced by each batting position, and innings per side in Tests. They use the five most recent seasons (internationals between Full Members, every league match), or every season when that gives fewer than 30 innings.

| Group | Balls per innings | Par | Innings per side | Innings measured |
|---|---:|---:|---:|---:|
| Men's Tests | 547.6 | 325.0 | 1.89 | 185 |
| Men's ODIs | 279.5 | 264.1 | 1 | 287 |
| Men's T20Is | 118.3 | 171.8 | 1 | 401 |
| Women's ODIs | 281.1 | 236.9 | 1 | 239 |
| Women's T20Is | 118.8 | 142.7 | 1 | 333 |
| Men's T20 leagues | 118.2 | 169.0 | 1 | 2,685 |

All six come from 2022–26.

**Win chances.** An edge in runs says nothing about chances until it is compared with real results. [src/best_eleven/model/calibrate.py](../src/best_eleven/model/calibrate.py) does that on every build:

1. Every completed match in a site scope (internationals between Full Members, every league match) gives two real elevens. Each player is rated from that scope's seasons in the four years before the match, with a three-year half-life, so the match itself never feeds its own forecast. Priors are left out: they use the whole archive and would leak later seasons into earlier matches, so a player with no record in the window counts as average, and so do overs no rated bowler covers (a real eleven's unknown player is a selected cricketer, not a batter forced to bowl). The batting order is the side's first-innings order, then anyone who did not bat. The site's own engine projects the edge, through [site/cli/versus-calibrate.mjs](../site/cli/versus-calibrate.mjs).
2. Some matches are left out: no results, matches decided by a rain rule or awarded, ties settled by a super over, limited-overs matches with shortened innings, and matches where either side has fewer than six players with a record in the window. A side of newcomers projects as average by construction, and the page compares rated players. The October build kept 10,608 matches.
3. Limited overs: `P(side A wins) = 1 / (1 + e^(−k × edge))`, with no intercept, so equal sides are even; a tie counts as half a win. Tests use an ordered model with a draw band: `P(A wins) = σ(k × edge − c)`, `P(B wins) = σ(−k × edge − c)`, and the draw takes the rest. A home-side term is fitted at the same time (home side from section 3), so home advantage does not inflate `k`. The stored `k` and `c` are the neutral-venue values.
4. Parameters are fitted on matches up to 2020. Matches from 2021 onwards are held out and scored with the Brier score and log loss. The naive forecast is a coin flip in limited overs; in Tests it is the training years' draw rate, with decisive results split evenly.
5. A group gets win chances only if its training years already show the curve holds up. Each of the last three training seasons is forecast from a fit on the seasons before it, and together those forecasts must beat the naive one on Brier score. The held-out years take no part in that decision.

| Group | Fitted on | k | Home advantage | Held out (2021–26) | Brier, model vs naive | Log loss, model vs naive | Favourite won |
|---|---|---:|---:|---:|---|---|---:|
| Men's Tests | 640 (2003–20) | 0.0077, c 0.54 | 78 runs | 217 | 0.581 vs 0.613 | 0.981 vs 1.009 | 60% |
| Men's ODIs | 1,339 (2003–20) | 0.042 | 8 runs | 302 | 0.218 vs 0.249 | 0.630 vs 0.693 | 68% |
| Men's T20Is | 476 (2007–20) | 0.049 | 2 runs | 474 | 0.225 vs 0.250 | 0.642 vs 0.693 | 65% |
| Women's ODIs | 177 (2011–20) | 0.052 | 3 runs | 257 | 0.160 vs 0.249 | 0.487 vs 0.693 | 77% |
| Women's T20Is | 279 (2010–20) | 0.096 | 4 runs | 340 | 0.187 vs 0.250 | 0.565 vs 0.693 | 71% |
| Men's T20 leagues | 2,548 (2009–20) | 0.044 | 3 runs | 2,720 | 0.244 vs 0.249 | 0.684 vs 0.693 | 55% |

The Test Brier score adds up the squared errors over win, draw and loss, so it runs higher than the two-outcome scores. "Favourite won" counts decisive results only. Home advantage is the home term divided by `k`, in runs per match.

As a guide, a 10-run edge makes a men's T20I side a 62% favourite, and a franchise T20 side 61%. A 20-run edge in a men's ODI gives 69%. In a Test, a 100-run edge gives 56% to win, 23% to draw and 21% to lose; level sides get 37% each with a 26% chance of a draw.

**Groups without win chances.** The page still projects runs for these, but shows no percentages:

- Women's T20 leagues. Forecasts of 2019 and 2020 from earlier seasons scored 0.251 against 0.250 for a coin flip, so the group was not calibrated. The held-out years agree: 0.253 against 0.249.
- The men's and women's Hundred. Both began in 2021, so nothing comes before the split to fit on.
- Women's Tests. Only 24 matches.

**What the chances mean, and what they don't.** They describe a neutral venue, an average pitch and no toss. Form counts only through the window and its recency weighting. Conditions, injuries, tactics and the toss are all outside the model. In franchise T20 the chances stay close to even: player ratings explain little of who wins there. Draw chances in Tests reflect 2003–20. From 2021, held-out Tests ended in a draw less often than forecast: 12% against about 23%.

One leak remains. The opposition adjustment in section 3 is fitted on the whole archive, so a player's adjusted record before a held-out match carries opponent and context effects estimated partly from later matches. The held-out scores may therefore flatter the model slightly.

### What the calibration does not cover

The win-chance curve was fitted on real elevens picked for the match format. A side picked elsewhere (the Test World XI in an ODI) or in a free shape leans more on predicted ratings and on the part-time bowling rate, which the curve never saw; the page says so beside the chances. The debut check in section 10 measures how good those predictions are for newcomers.

## 10. Validation

[src/best_eleven/validate.py](../src/best_eleven/validate.py) runs on every build. The debut-prior check (section 4) refits the transitions on seasons before 2019 and fails if, in any format with at least 25 debutants since, the prior does not beat the zero prior on their first two seasons. The XI vs XI check runs after export, because it rates players from the exported scopes. The build fails when any calibrated group with at least 200 held-out matches does not beat its naive forecast on Brier score. The results are in [docs/ASSURANCE.md](ASSURANCE.md) and on the site's method page.
