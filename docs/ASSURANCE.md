# Assurance

What has been checked, how, and what remains open. Status as of 9 October 2026; the career check was revised on 22 October 2026.

## Checks that run on every build

[src/best_eleven/validate.py](../src/best_eleven/validate.py) runs inside `best-eleven build`. The Pages workflow does not publish when a check fails, so the live site keeps the last good build.

The weekly build of 19 October 2026 failed the career check: it then compared whole careers with infoboxes frozen at the 9 October snapshot, so the Australia v South Africa Test of 9–13 October put 20 players one match ahead of Wikipedia. The check now counts like for like (below). Its freshness window had the same flaw: measured from the latest match, it would have emptied the strict set within two months of any snapshot.

| Check | Method | Result (Oct 2026) |
|---|---|---|
| Ingest accounting | Rebuild each innings total from deliveries; compare with every official winning margin by runs (including innings victories) and by wickets | 9,981 of 9,985 run margins and 10,326 of 10,327 wicket margins exact. The five misses are associate matches whose source totals disagree with their own result. |
| Identity and completeness | Compare Cricsheet career totals with Wikipedia infoboxes for men's Test players whose careers lie wholly inside coverage, from sides that have never met Afghanistan in a Test, with infoboxes updated within 60 days of the reference snapshot. Cricsheet is counted only up to the date each infobox gives for its figures, so matches played after the snapshot cannot fail the check and the set does not shrink as data arrives. Left out: infoboxes dated inside a match the player was playing, or after the last Cricsheet match. Fails below 50 players or 98% exact | 123 players, 100% exact on matches, runs and wickets (data to 14 Oct 2026) |
| Broad completeness (context) | Same comparison for every player, counted to each infobox's date where it gives a full one | Exact for 70% of Test, 41% of ODI and 42% of T20I players. Where Cricsheet has fewer matches, the misses concentrate in sides that play Afghanistan (Cricsheet withholds those matches). Cricsheet has more for 1–4% of players; before counting to the infobox date it was 8–17%, mostly matches played after an infobox was last updated. |
| Does the adjustment help? | Rating from 2016–21 vs raw output per ball in 2022–26, batters with 300+ balls in both (Spearman) | Adjusted beats raw value per ball in Tests (0.64 vs 0.60), ODIs (0.45 vs 0.40), T20Is (0.35 vs 0.31) and the IPL (0.40 vs 0.35). In T20Is, plain strike rate (0.44) beats both. |
| Bowling-type classifier | 5-fold cross-validation on 3,210 bowlers with Wikipedia styles | 89% accuracy, AUC 0.965; at the 0.85 threshold, 88% of bowlers labelled with 94% accuracy |
| Selector exactness | 120 random instances (caps, locks, exclusions) solved by the browser engine and by SciPy's MILP | Identical optima |
| Debut priors | Refit the format-to-format transitions on seasons before 2019; for every player who debuted in a format from 2019 on, predict his first two seasons there from what he had done before his debut; ball-weighted squared error against the old zero prior and the plain newcomer baseline. Fails if the prior loses to the zero prior in any format with 25+ debutants | Prior vs zero prior: men's Tests batting 0.064 vs 0.067 (132 debutants), bowling 0.048 vs 0.049 (140); ODIs 0.056 vs 0.090 (203), 0.050 vs 0.054 (221); T20Is 0.197 vs 0.329 (417), 0.170 vs 0.207 (507); women's ODIs 0.076 vs 0.126 (75), 0.049 vs 0.058 (115); T20Is 0.303 vs 0.812 (154), 0.214 vs 0.355 (273). The prior also beat the newcomer baseline in all ten. Women's Tests: too few debutants to judge |
| XI vs XI win chances | Rate both real elevens of 10,608 completed matches from the four seasons before each, project the edge with the site engine, fit the win-chance curve on matches to 2020, then score 2021–26 against a naive forecast (coin flip; for Tests the training draw rate). Fails if any calibrated group with 200+ held-out matches loses on Brier score | Brier, model vs naive, on held-out matches: men's Tests 0.581 vs 0.613 (217), ODIs 0.218 vs 0.249 (302), T20Is 0.225 vs 0.250 (474); women's ODIs 0.160 vs 0.249 (257), T20Is 0.186 vs 0.250 (340); men's T20 leagues 0.244 vs 0.249 (2,720). Favourites won 55% (T20 leagues) to 77% (women's ODIs) of decisive results. |

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
- XI vs XI shows no win chances for women's T20 leagues, the Hundred or women's Tests. In women's leagues, forecasts within the training years did no better than a coin flip (0.251 vs 0.250), and neither did the held-out years (0.253 vs 0.249). The Hundred began in 2021, after the fitting years, and women's Tests are too few.
- XI vs XI held-out scores may be slightly optimistic: the opposition adjustment behind every rating is fitted on the whole archive, later matches included. Test draws were forecast at about 23% for 2021–26; 12% happened.
- The rule that withholds win chances from a group (forecasts within the training years must beat the naive one) was added after the held-out results for women's T20 leagues had been seen. It uses only training years, but it was not set in advance.

## Process notes

This build was produced with one AI provider. The OmniMind contract asks for independent cross-provider review on changes of this size; that review has not happened yet and is owed.
- Priors for short records use no first-class data (it is not in the ratings), so Test priors rest on white-ball and league records, the weakest transitions (correlation 0.3 to 0.5). A prior uses a player's whole archive record, later seasons included: right for all-time and fantasy sides, but a historical window can know how a career turned out.
- XI vs XI win chances are calibrated on real elevens picked for the match format, rated without priors. A side picked from another format, or built in a free shape, leans on predicted ratings and on the part-time bowling rate, which that calibration never tested.
