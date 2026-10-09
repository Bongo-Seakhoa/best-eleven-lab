# Data dictionary

## Warehouse (`data/warehouse`, rebuilt by `best-eleven ingest`)

Player columns hold integer codes; `players.parquet` maps codes to Cricsheet's eight-hex ids and names.

| Table | Grain | Key columns |
|---|---|---|
| `matches.parquet` | match | `match_id`, `source_file`, `start_date`, `year`, `match_type`, `format`, `family` (multi, fifty, t20, hundred), `gender`, `team_type`, `scope`, `event`, `team1`, `team2`, `venue`, `city`, `toss_*`, `winner`, `result`, `by_runs`, `by_wickets`, `innings_runs`, `method`, `bpo` |
| `players.parquet` | person | `player`, `id`, `name` (latest spelling), `first_date`, `last_date` |
| `appearances.parquet` | player × match | `match_id`, `team`, `player`, `replacement`, `supersub` |
| `innings.parquet` | innings | `batting_team`, `bowling_team`, `super_over`, `declared`, `target_runs`, `target_balls`, `runs`, `wickets`, `legal_balls`, `max_balls`, penalties |
| `deliveries/<scope>.parquet` | ball | `inning`, `ordinal`, `over`, `legal_before`, `batter`, `non_striker`, `bowler`, `runs_batter`, `runs_extras`, `runs_total`, extras by type, `four`, `six`, `legal`, `faced`, `conceded`, `score_before`, `wkts_before`, `striker_out`, `striker_kind`, `bowler_wkt`, `ns_out`, `fielder`, `batter_pos`, `phase` (0–2), `balls_rem`, `target`, `super_over` |
| `wickets.parquet` | dismissal | `player_out`, `kind`, `is_out`, `bowler_credit`, `bowler`, `fielder1/2` (+ substitute flags) |
| `batting.parquet` / `bowling.parquet` | player × innings | scorecard figures, batting position, maidens |
| `manifest.json` | build | archive checksum, counts per scope, quarantine list |

Wicket kind codes: 1 caught, 2 bowled, 3 lbw, 4 run out, 5 caught and bowled, 6 stumped, 7 hit wicket, 8 retired hurt, 9 retired out, 10 retired not out, 11–14 rarer modes.

## Model outputs (`data/model`)

| File | Contents |
|---|---|
| `values/<scope>.parquet` | deliveries with `contest` (run value), `bat_adj` (credited to the batter), `bowl_cost` (charged to the bowler), `ns_value`, `ctx`, `home`, `bat_full`/`bowl_full` |
| `seasons/<scope>.parquet` | additive sums per player × year × team × opposition class (see below) |
| `keepers.parquet` | inferred wicketkeeper per match and side, with method (`stumping` or `record`) |
| `bowler_family.parquet` | classifier output (`p_spin`, `family`) for bowlers without a Wikipedia style |
| `values_summary.json`, `validation.json`, `bowler_family_metrics.json` | fitted parameters and check results |

Season columns (also the site's `seasons` arrays):

- **Matches and keeping:** `m` matches, `kp` kept wicket.
- **Batting:** `bi` innings, `no` not outs, `r` runs, `b` balls, `o` outs, `f4`/`f6`, `d0` dots, `h50`/`h100`, `hs`, `p12`/`p3`/`p46`/`p7` innings by batting position, `ba` adjusted batting value.
- **Bowling:** `wi` innings, `wb` legal balls, `wr` runs conceded, `ww` wickets, `wm` maidens, `wd` dots, `wx`/`wn` wides and no-balls, `wc` adjusted bowling cost, `wp0..2` balls by phase, `w3`/`w5` hauls.
- **Fielding:** `ct` catches, `kc` keeper catches, `st` stumpings, `ro` run-outs.

## Reference snapshots (`data/reference`, versioned)

Every row carries `source_page` and `revid`.

| File | Grain | Highlights |
|---|---|---|
| `players_wiki.csv` | Wikipedia article | Cricsheet/cricinfo/Wikidata ids, `birth_date`, `country`, `batting_hand`, `bowling_class` (RF RFM RMF RM LF LFM LMF LM OB LB SLA LWS), `bowling_family`, `role`, `international_span`, `retired_test/odi/t20i/international` with `retirement_evidence`, `career_json` (infobox totals per format) |
| `careers_lists.csv` | player × country × format list | cap, span, batting and bowling totals, catches, stumpings, captain and keeper markers |
| `captains.csv` / `captain_totals.csv` | source row / captain × team × format | played, won, lost, drawn, tied, no result, win %, span |
| `squads.csv` | squad place | team, competition, formats, contract, `captain_formats`, `vice_captain_formats`, `captain` (bare C/VC), `overseas`, `status`, `as_of`, `page_timestamp` |
| `manifest.json` | refresh | fetch date and source |

## Site data (`site/data`, rebuilt by `best-eleven export`)

| File | Contents |
|---|---|
| `meta.json` | build time, data end date, archive checksum, scope list, model parameters, profile counts |
| `scopes/<key>.json` | `players` arrays (ids, names, national side, hand, style, family and its source, role, availability flags `squad`/`active`/`retired`, `capt`, `vc`, `cc` current captain, `pre` caps before coverage, `overseas`), `teams` with `teamsFull`, and columnar `seasons` |
| `historic/<key>.json` | all-eras career pools with decade baselines |
| `players/index.json`, `players/<id>.json` | directory entries and full profiles |
| `captains.json`, `validation.json`, `reference.json`, `model/*.json` | captaincy table, checks, reference summary, run expectancy, classifier metrics |
