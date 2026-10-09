# Assurance and handoff

**Delivery:** Best Eleven 0.1, research prototype. **Decision:** deliver the working local package and explicitly synthetic preview; do not call real-data research, public publication or formal independent acceptance complete.

## Observed verification

| Check | Observed result |
|---|---|
| Automated tests | 50 passing tests: accounting, identity/revision behavior, per-match rollback, unsafe ZIPs, partial imports, real/demo separation, metadata dates, team scopes, optimization, profile exposure, fantasy, temporal diagnostics, source mocks and API behavior. |
| End-to-end synthetic pipeline | 108 generated matches, 36 per format; 64 fictional roster identities; 60,441 delivery records. Repeat generation leaves all 108 matches unchanged. |
| Selection | Valid, unique elevens across Test/ODI/T20 under the demonstrated policies. Infeasible constraints return no XI; returned assignments are checked independently of solver status. |
| Notebook | The 19-cell notebook ran top to bottom: all nine code cells executed; eight retain outputs, including four figures. Figures were visually inspected. The notebook and its HTML rendering are included. |
| Package entry point | Editable installation completed in the available environment; CLI selection, evaluation and self-contained preview exports executed. |
| Offline browser | Chromium rendered the actual self-contained UI. Format switching, saved policy changes, profiles and sensitivity operated. No JavaScript page errors were observed. The 390-pixel viewport had no document-level horizontal overflow. Desktop, player and mobile screenshots were inspected. |
| Local API | FastAPI TestClient exercised the real application functions. Additional calls verified the inclusion-cost response and rejection of an invalid upload. A launched local HTTP server answered its health/status endpoint. |
| Full browser-to-server navigation | **Blocked by the environment’s browser navigation policy.** This is not reported as a pass. The optional browser script records the block and exits nonzero while retaining passed offline checks. |
| Provider network acquisition | **Not completed.** Documentation was readable, but bulk ZIP retrieval was unavailable from the execution environment. Tests used controlled archives and HTTP responses; they do not establish successful live retrieval. |
| GitHub | **Not published.** The connected interface exposed read-only repository operations and there was no authenticated `gh` CLI. A reviewed-file publication script is included, but its remote write has not been run. |
| Remote CI / manual refresh | Workflow definitions are included. Neither was run on GitHub; no recurring schedule or cloud job was enabled. |

The exact current test receipt and component versions are in `examples/verification.json`. The browser receipt is `examples/browser_verification.json`. These are test results, not invented confidence percentages.

## OmniMind status

The project’s user-requested operating rules were consulted, but the actual local OmniMind runtime and a second AI provider were not available in the execution environment. No runtime lane, PM verdict, independent cross-provider review or formal acceptance was fabricated. A cross-module project of this kind still needs independent review before it can be called formally accepted or production-ready.

Private operating documents, other projects, account secrets and unrelated user data are not copied into the public package.

## Material remaining work

The first scientific milestone is a **real, reconciled national dataset**, not another decorative UI pass. Obtain the actual archives, verify the reviewed schema against them, reconcile scorecard totals and coverage, resolve identity/role/appointment sources, and run the fixed national-study protocol without choosing a favorable comparator after the result.

The score is a declared heuristic. Opponent strength and conditions are not fully adjusted; the separate predictive diagnostic does not validate XI choice. No complete-career or all-time ranking and no verified finding about Temba Bavuma is present. Current availability and leadership evidence must be supplied rather than inferred.

The field-placement panel intentionally stays unavailable. Minimal tracking-shell checks do not establish measurement validity, legal field settings, overlap or causal identifiability. Full tracking and a validated research design are required before an optimum could be reported.

For operations, validate the local browser-to-server flow on an unrestricted local machine, run the source refresh and remote CI, review source terms, and obtain the outstanding independent review. Full-archive performance, withdrawn-match reconciliation and automatic metadata conflict resolution remain unvalidated or unimplemented. The local process has one writer lock, not a distributed multi-user job system. Do not expose it directly as a public service.

## Reproduce the checks

```bash
python -m pip install -e '.[dev]'
pytest -q
python -m jupyter nbconvert --execute --to notebook --inplace notebooks/01_selection_and_matchups.ipynb
python -m pip install -e '.[ui]'
python -m playwright install chromium
python scripts/verify_browser.py
```

A system Chromium installation can be passed with `--chromium /path/to/chromium`. The notebook only generates fictional data in a temporary database and removes it when complete. The browser script has a separate temporary database. No test calls the live data provider.

The reviewed-public-file manifest helps prevent accidental publication of unrelated files. It is a checksum list, not a digital signature or proof of independent review. Validate only with `python scripts/publish_github.py --owner YOUR_ACCOUNT`; add `--publish` solely when deliberately creating a new public repository.
