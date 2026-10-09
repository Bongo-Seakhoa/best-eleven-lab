# Best Eleven working contract

Read README.md, docs/METHODOLOGY.md and docs/ASSURANCE.md before changing behaviour.

- National teams across Test, ODI and T20I come first; leagues share the same model.
- One implementation per concern. Python owns ingestion, valuation, adjustment and export. `site/assets/js/engine` owns selection, and the CLI's `select` calls that same engine through Node. Do not add a second selector or scorer.
- Keep formats, sources, time windows and role rules explicit. Missing data stays missing: never turn an absent squad, style or captaincy record into an inferred fact without labelling it as inferred (as the bowling-type classifier does).
- Never replace a failed download or an infeasible selection with plausible-looking output. Report the failure.
- Tests stay network-free (fixtures under `tests/fixtures`). Real-source acquisition (`fetch`, `enrich`) is an explicit operation.
- Reference snapshots in `data/reference` change only through `best-eleven enrich` and review (the refresh workflow opens a pull request).
- `best-eleven build` must pass validation before the site is published; do not weaken a check to make a build pass.
- No player photographs. Team logos are identification only, with credits.
- Commits carry no AI attribution trailers.
