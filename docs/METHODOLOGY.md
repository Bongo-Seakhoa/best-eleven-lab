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

## 9. Validation

[src/best_eleven/validate.py](../src/best_eleven/validate.py) runs on every build. The results are in [docs/ASSURANCE.md](ASSURANCE.md) and on the site's method page.
