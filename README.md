<p align="center"><img src="site/assets/img/social-card.png" alt="Best Eleven" width="720"></p>

# Best Eleven · cricket selection lab

Pick a cricket Best XI for any national side, franchise league or era, from every ball in [Cricsheet](https://cricsheet.org)'s archive and every international career on record since 1877.

**Live site: https://bongo-seakhoa.github.io/best-eleven-lab/**

- **Selection room.** Choose men's or women's Tests, ODIs or T20Is, or a league (IPL, SA20, BBL, PSL, CPL, WPL, WBBL and nine more). Pick a team or a World XI, a year window, and who is available: the current squad, active players or everyone. Then weigh quality, legacy, experience and leadership as you see fit. An exact solver returns the best eleven for that composition, with the captain, keeper, next in line, "why not X?" and a robustness check.
- **All eras.** A second evidence base built from complete career records (Tests from 1877, ODIs from 1971), adjusted to each decade's average, so Bradman, Barry Richards or Graeme Pollock can sit alongside today's players.
- **Player profiles** for 6,694 cricketers. Each shows ratings, season trends, how the player fares against each bowling type or batting type, by phase, how they get out (or take wickets) compared with their peers, the bowlers or batters they meet most, and a field plan built from their measured rates.
- **Player database** that knows who is actually available: current national and franchise squads, reported retirements and come-backs, captaincy and vice-captaincy, batting hand, bowling style and career totals.
- **Captains** compared side by side from formal captaincy records.

## How it works

```
Cricsheet all_json.zip ─► ingest ─► Parquet warehouse (23,080 matches, 11.7 m deliveries)
                                         │
Wikipedia / Wikidata ─► enrich ─► data/reference (players, squads, captaincy, careers, team images)
                                         │
                       model ─► run expectancy ─► value of every ball ─► opposition / era / venue
                                adjustment (ridge) ─► season aggregates ─► bowling-type classifier
                                         │
                       validate ─► margins, career totals, out-of-sample check, classifier CV
                                         │
                       export ─► site/data (JSON) ─► static site: selection runs in your browser
```

Every limited-overs ball is valued by how much it changes the batting side's expected total. The run-expectancy surface is fitted by era, with a Duckworth–Lewis-style curve per wickets lost. In Tests, a ball is worth its runs minus each dismissal priced at that year's runs per wicket. A ridge regression on batter, bowler, both sides and context (era × phase × innings × home) then removes who a player faced and where. Empirical-Bayes shrinkage keeps short records from dominating. The selector turns your weights into one score per player per slot and solves the assignment exactly as a min-cost flow. That solver is checked against an integer program on every test run. [docs/METHODOLOGY.md](docs/METHODOLOGY.md) has the details.

## Checks on every build

| Check | Latest result |
|---|---|
| Winning margins rebuilt from deliveries | 99.96% of 9,985 run margins and 99.99% of 10,327 wicket margins exact |
| Career totals vs Wikipedia (strict set: careers wholly inside coverage, fresh infoboxes) | 124 Test players, 100% exact on matches, runs and wickets |
| Earlier rating vs later output (Spearman, batters) | adjusted beats raw in Tests 0.64 vs 0.60, ODIs 0.45 vs 0.40, T20Is 0.35 vs 0.31, IPL 0.40 vs 0.35 |
| Pace/spin classifier (5-fold CV) | 89% accuracy, AUC 0.965; labels kept only above 0.85 confidence (94% accurate) |

The Pages workflow refuses to publish if a check fails. [docs/ASSURANCE.md](docs/ASSURANCE.md) records what was verified and what remains open.

## Run it yourself

Python 3.11+ and, for `select`, Node.js 18+.

```bash
python -m pip install -e ".[dev]"
best-eleven fetch            # Cricsheet archive and people register (conditional download)
best-eleven build            # ingest, model, validate, export (about 15 minutes)
best-eleven serve --open     # the site on http://127.0.0.1:8765
best-eleven select --scope men-test --team "South Africa" --availability squad
best-eleven enrich           # refresh the Wikipedia/Wikidata snapshots (network, ~20 minutes)
pytest -q
```

`select` accepts `--scope` (`men-test`, `women-odi`, `ipl`, `sa20`, …), `--from`/`--to`, `--preset` (`balanced`, `quality`, `form`, `legacy`, `experience`), `--availability`, `--max-per-team`, `--max-overseas` and `--json`.

## Automation

- **Tests** run on every push: Python, plus a parity check of the browser solver against SciPy's MILP.
- **Build and publish the site** runs on every push to `main` and every Monday. It downloads Cricsheet's latest archive, rebuilds everything, validates, and deploys to GitHub Pages.
- **Refresh the player database** is manual. It re-reads Wikipedia and Wikidata and opens a pull request, so squad, retirement and captaincy changes are reviewed before they reach the site.

## Repository

```
src/best_eleven/   ingest, enrich/ (Wikipedia, Wikidata, team images), model/, validate, export, cli
site/              index.html and assets: engine/ (selection), views/, ui/ (charts, icons), css/
data/reference/    versioned player-database snapshots; data/raw, warehouse and model are rebuilt
config/            competitions, league overseas rules with their sources
scripts/           render_grounds.py: renders the ground images behind field plans and the hero
site/assets/img/   rendered grounds, team flags and logos (with credits), brand mark
tests/             network-free tests and fixtures
```

## Limits worth knowing

- Cricsheet withholds matches involving Afghanistan's men, and men's ball-by-ball coverage starts around 2002.
- No ball-tracking or shot data exists, so field plans set the number of catchers, ring and boundary fielders from measured rates, while exact positions follow convention.
- Squads, retirements and captaincy come from Wikipedia and can lag. Overseas status is inferred from international appearances.

## Credits and licence

Match data from [Cricsheet](https://cricsheet.org) (ODC-By 1.0). Player attributes, squads, captaincy and historic careers from Wikipedia and Wikidata (CC BY-SA 4.0 / CC0). Team flags from Wikimedia Commons; franchise logos belong to their owners and are shown only to identify teams. This is a non-commercial fan project, not affiliated with any board, league or franchise. See [DATA_NOTICE.md](DATA_NOTICE.md) and the site's Credits page. Code: MIT.
