# Reference and planning results

This directory contains two different evidence classes.

## `reference_summary.csv`

A pinned summary of the current **v0.25** deterministic reference run (`seed=2206`, `days=120`). The values were reproduced by GitHub Actions after the retention-maturity and look-ahead safeguards were added.

The authoritative full build is the generated `reference-evidence` workflow artifact. It includes the full CSV/JSON evidence set, `workbench.duckdb`, and `MANIFEST.json`.

v0.25 reports activity retention only from cohorts whose target date is on or before the declared `analysis_as_of`. The separate maturity outputs show how many users are currently eligible versus excluded because their D7/D30 horizon has not matured yet.

## `risk_aware_design.csv`

A preserved planning snapshot from the broader pre-v0.23 unequal-randomisation study. The compact public package retains allocation/evidence-planning primitives but not the entire historical Monte Carlo portfolio-risk engine.

Accordingly, this file is methodological context rather than a current-workflow regression target or production recommendation.

## Reproduce the current reference

```bash
make reference
make validate
```

See `docs/REPRODUCIBILITY.md` for the provenance rule used throughout the repository.
