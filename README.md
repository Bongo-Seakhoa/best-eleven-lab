# Best Eleven
### Pick a side. Make the case.

An evidence-first cricket selection and player-analysis lab. National teams across **Test, ODI and T20** come first. IPL, SA20, Big Bash and PSL use the same ingestion framework as the second tier.

**Status: working research prototype, not a validated cricket-selection product.** The delivered preview and notebook use explicitly fictional records. Bulk live-source retrieval, real-scorecard reconciliation, public GitHub publication and independent cross-provider acceptance were not completed in the build environment. The code includes the acquisition path; the existence of that path is not evidence that live acquisition has been validated.

![Selection room, using explicitly fictional players](docs/selection-preview.png)

## Start here

Open **`BEST_ELEVEN_PREVIEW.html`** for a self-contained demonstration. It uses the same interface and Python-generated calculations as the local application, with saved scenarios for all three formats. Data refresh, uploads, arbitrary weights and custom constraints require the local application; the preview does not pretend to perform them.

Use Python 3.11 or later. From the extracted project directory:

```bash
python -m venv .venv
# Windows PowerShell: .\.venv\Scripts\Activate.ps1
# macOS / Linux: source .venv/bin/activate
python -m pip install -e ".[dev]"
best-eleven --db data/demo.sqlite demo
best-eleven --db data/demo.sqlite serve --open
```

The server binds to `127.0.0.1:8765`. Select **Synthetic demonstration** in the evidence selector. The real-data view starts empty and never silently substitutes fictional players.

## What works

| Area | Implemented behavior |
|---|---|
| Acquisition | Allowlisted Cricsheet ZIP sources, conditional HTTP refresh, bounded retries, manual ZIP import, content-addressed raw archives, receipts and checksums |
| Storage | Local SQLite, stable player IDs, integer delivery identity, revision-aware per-match transactions, quarantine of invalid matches |
| Selection | Eleven unique players; role-compatible slots; batting, bowling, keeper, opener, pace/spin, availability, budget and team-count constraints; lock/exclude options |
| Preferences | Performance, observed experience, documented leadership and sampling caution; explicit contribution accounting; four-policy sensitivity checks |
| Player lab | Individual opponents, national opponents, over bands, seasons and venues; bowling-style and batting-hand splits when supplied; bowling profiles by batting-order archetype |
| Uncertainty | Match-cluster bootstrap intervals for descriptive rates; sample counts and sparse-evidence labels; missing evidence is not a claim of strength or weakness |
| Research | Chronological predictive diagnostic against a pooled baseline; executed notebook; field-policy data gate and research design |
| Fantasy | CLI-only, explicit research scoring, historical points per roster appearance, optional credits/team limits, separate fantasy captain multipliers |

The local app has Selection room, Player lab, Data & pipeline and The method views. The CLI exposes the same analysis functions, plus fantasy and preview exports.

## Acquire real national data

Start with the country archive to exercise ingestion. Then fetch the international format archives for a broader peer population; a South-Africa-only archive is not an unbiased worldwide benchmark.

```bash
best-eleven fetch south_africa_male
best-eleven fetch tests_male
best-eleven fetch odis_male
best-eleven fetch t20s_male
best-eleven coverage
best-eleven select --format Test --team "South Africa" --as-of 2026-10-09 --output results/south-africa-test.json
best-eleven serve --open
```

Women’s sources are `tests_female`, `odis_female` and `t20s_female`; choose `--gender female`. The source manifest is a list of supported URLs, not a guarantee of complete or current provider coverage. A source schema outside reviewed versions 1.0.0 and 1.1.0 fails closed.

When the provider’s automated-download endpoint is inaccessible, obtain its archive through your browser, then use the app’s **Import its ZIP** control or:

```bash
best-eleven ingest /path/to/source.zip --source tests_male --provenance https://cricsheet.org/downloads/tests_male_json.zip
```

Both fetches and imports retain one content-addressed raw copy. Repeated archives and overlapping country/format archives do not duplicate match records. Import provenance is user-asserted, not independently authenticated. A partial import has an explicit `partial` status and a nonzero CLI exit code; inspect the quarantine before using results.

### Roles and other missing attributes

Basic usage can suggest roles. A recorded stumping can provide wicketkeeping evidence; absence of stumpings does not establish that someone cannot keep wicket. A reliable selection needs reviewed roles, not only usage inference.

Import **`config/metadata-template.csv`** after replacing it with source-attributed rows. The contract includes player ID, format, team level, effective dates, observed date, role, batting hand, bowling style, team, captain/vice-captain counts, credit and availability. Empty fields stay unknown. Rows are complete snapshots; the application does not merge conflicting fields from different sources.

```bash
best-eleven metadata my-reviewed-metadata.csv
best-eleven select --team "South Africa" --format Test --preferences config/strict-national.json
```

The strict policy requires dated roles and availability. A sourced URL records provenance; it is not automated verification that the source is accurate. Captain and vice-captain counts must refer to the declared format and level and be known at the recorded observation date.

## Reproduce an output

```bash
best-eleven --db data/demo.sqlite rank --dataset demo --format Test --team "Cedar XI (demo)"
best-eleven --db data/demo.sqlite select --dataset demo --format ODI --team "Cedar XI (demo)" --preferences config/performance-only.json
best-eleven --db data/demo.sqlite sensitivity --dataset demo --format Test --team "Cedar XI (demo)"
best-eleven --db data/demo.sqlite evaluate --dataset demo --format Test --as-of 2026-10-09
best-eleven --db data/demo.sqlite export-preview --dataset demo --team "Cedar XI (demo)" --as-of 2026-10-09 --output preview.html
pytest -q
```

`profile PLAYER_ID` and `why-not PLAYER_ID` accept the same scope arguments. Obtain the stable ID from a ranking export. `--db` is a global option and goes before the command.

For league research, use `fetch ipl`, `fetch sa20`, `fetch bbl` or `fetch psl`, then `--format T20 --level club`. The fantasy command uses **research rules**, not current official rules from a fantasy platform:

```bash
best-eleven fantasy --format T20 --level club --competition "Indian Premier League" --rules config/fantasy-research.json --output results/fantasy.json
```

Copy competition names from `coverage`; the example spelling must match the imported event name. Official fantasy squad lists, current player prices, overseas-player rules and platform-specific bonuses require reviewed inputs. The current fantasy CLI does not claim an official eligible team.

## The field-placement boundary

A successful catcher is not a measured catch location. A dot ball is not measured runs saved. A field that creates wickets can also open gaps. This release therefore returns **no optimal-field recommendation** from ordinary delivery outcomes.

[Field-policy research design](docs/FIELD_RESEARCH.md) specifies the full delivery universe, pre-delivery field layouts, trajectories, match context and identification checks needed to progress. The implemented gate is a minimum structural check, not a tracking validator or a causal model.

## The Bavuma question

The project does not publish a verdict on Temba Bavuma. That comparison needs a defined role, format, historical cohort and evidence period, then real-data reconciliation. [The first national study protocol](docs/research/BAVUMA_PROTOCOL.md) freezes those questions without predetermining the answer. Ball-by-ball coverage must not be labelled a complete career or an all-time record.

## Architecture

```text
Cricsheet or supplied ZIP → bounded acquisition → immutable raw archive + receipt
                                                ↓
                           revision-aware SQLite match / innings / delivery tables
                                                ↓
                            scope → peer baselines → player features → role MILP
                                                ↓
                              XI + explanations + player profiles + JSON export
```

Python + SQLite + SciPy/HiGHS + FastAPI + a dependency-free HTML/CSS/JavaScript frontend. No warehouse credentials, paid API or cloud database is required by this implementation. Internet access is needed to install packages and retrieve live source archives. Run one local writer at a time; this release is not a public multi-user service.

## Verification and boundaries

See [ASSURANCE.md](docs/ASSURANCE.md) for the exact observed checks and outstanding release gates. See [METHODOLOGY.md](docs/METHODOLOGY.md) for every score, denominator, prior and material limitation. The executed notebook is **`notebooks/01_selection_and_matchups.ipynb`**.

The public-ready package excludes downloaded provider data, databases, credentials and private OmniMind material. The code is MIT; third-party datasets retain their own terms. See [DATA_NOTICE.md](DATA_NOTICE.md).

## GitHub publication

No remote repository was created during this build: the connected GitHub functions were read-only and no authenticated GitHub CLI was available. After reviewing the package and completing independent review, run the included `scripts/publish_github.py` from an environment with Git and an authenticated `gh` CLI:

```bash
python scripts/publish_github.py --owner Bongo-Seakhoa --name best-eleven-lab --publish
```

The script verifies the authenticated account and creates a **new public repository**. It refuses an existing remote and does not change any existing repository’s visibility. The included GitHub Actions definitions are unexecuted configuration: CI tests the package, and a **manual-only** refresh workflow fetches a selected source and returns analysis artifacts. No schedule is enabled.
