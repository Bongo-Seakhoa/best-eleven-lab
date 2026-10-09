# Assurance

What has been checked, how, and what remains open. Status as of 9 October 2026.

## Checks that run on every build

[src/best_eleven/validate.py](../src/best_eleven/validate.py) runs inside `best-eleven build`. The Pages workflow does not publish when a check fails, so the live site keeps the last good build.

| Check | Method | Result (Oct 2026) |
|---|---|---|
| Ingest accounting | Rebuild each innings total from deliveries; compare with every official winning margin by runs (including innings victories) and by wickets | 9,981 of 9,985 run margins and 10,326 of 10,327 wicket margins exact. The five misses are associate matches whose source totals disagree with their own result. |
| Identity and completeness | Compare Cricsheet career totals with Wikipedia infoboxes for men's Test players whose careers lie wholly inside coverage, from sides that have never met Afghanistan in a Test, with infoboxes updated within 60 days | 124 players, 100% exact on matches, runs and wickets |
| Broad completeness (context) | Same comparison for every player | Exact for 70% of Test, 37% of ODI and 39% of T20I players. Where Cricsheet has fewer matches, the misses concentrate in sides that play Afghanistan (Cricsheet withholds those matches). Where it has more, women's infoboxes last updated in 2023–24 explain it. |
| Does the adjustment help? | Rating from 2016–21 vs raw output per ball in 2022–26, batters with 300+ balls in both (Spearman) | Adjusted beats raw value per ball in Tests (0.64 vs 0.60), ODIs (0.45 vs 0.40), T20Is (0.35 vs 0.31) and the IPL (0.40 vs 0.35). In T20Is, plain strike rate (0.44) beats both. |
| Bowling-type classifier | 5-fold cross-validation on 3,210 bowlers with Wikipedia styles | 89% accuracy, AUC 0.965; at the 0.85 threshold, 88% of bowlers labelled with 94% accuracy |
| Selector exactness | 120 random instances (caps, locks, exclusions) solved by the browser engine and by SciPy's MILP | Identical optima |

## One-off verification (October 2026)

**Captaincy snapshot.** Checked by an independent reviewer against the live pages: 28 table layouts, and 319 captain aggregates matching the pages' own total rows. Examples confirmed include Ponting 77 Tests, Dhoni 200 ODIs and 72 T20Is, Bavuma 12 Tests (11 won), Meg Lanning 78 ODIs, Williamson 40 Tests, and IPL captains. The seven remaining mismatches are inconsistencies inside the source pages; they are kept as published and flagged. 23 sampled identity links were confirmed as the same person.

**Retirement detection.** Spot-checked as correct for Kohli and Rohit Sharma (Tests and T20Is), Steve Smith (ODIs), Stokes (international, June 2026), Broad and Steyn. Come-backs are honoured: Shabnim Ismail reversed her retirement in May 2026, and Dane van Niekerk's 2025 T20I appearance overrides her 2023 retirement statement.

**Current squads.** Twelve national sections are older than 15 months on Wikipedia, South Africa women's (July 2022) among them; they no longer count as current squads. 93% of linked squad players have appearances for that team.

**Historic careers.** Spot checks against the lists: Kallis (13,206 Test runs for South Africa), Tendulkar 15,921, Muralitharan 795 for Sri Lanka, Bradman 99.94, Warne 708, Mithali Raj 7,805 ODI runs. All 681 name-matched identity links were confirmed by appearances for that country, format and gender.

**Sense checks on selections.** The current South Africa Test XI from the current squad comes out Markram, Rickelton, Stubbs, Bedingham, Bavuma (c), Mulder, Verreynne (wk), Bosch, Jansen, Harmer, Rabada. The all-eras World Test XI is Bradman, Weekes, Hammond, Barrington, Smith, Walcott, Imran Khan, Lohmann, Ambrose, Muralitharan, McGrath.

## Known gaps

- Cricsheet withholds every match involving Afghanistan's men (379 matches at the October archive). Afghanistan's men have no ball-by-ball ratings, and their opponents' records are short by those games.
- Men's ball-by-ball coverage starts around 2002. Earlier careers enter only through the all-eras mode, which has no batting positions, strike rates or opposition adjustment.
- Field plans have no spatial data behind the named positions.
- Squads, retirements and captaincy come from Wikipedia text and tables and can lag the real world. Vice-captaincy is known only for current squads.
- Overseas status is inferred from international appearances or Wikipedia nationality, not from league registrations.
- Women's Tests (24 matches) are too few to adjust for opposition.

## Process notes

This build was produced with one AI provider. The OmniMind contract asks for independent cross-provider review on changes of this size; that review has not happened yet and is owed.
