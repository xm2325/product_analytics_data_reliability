# Reference and planning results

This directory contains two different evidence classes.

## `reference_summary.csv`

A pinned summary of the current **v0.24** deterministic reference run (`seed=2206`, `days=120`). The values were reproduced by GitHub Actions after the explicit `app_open`, DAU migration and retention upgrades.

The authoritative full build is the generated `reference-evidence` workflow artifact, which includes the full CSV/JSON evidence set, `workbench.duckdb`, and `MANIFEST.json`.

## `risk_aware_design.csv`

A preserved planning snapshot from the broader pre-v0.23 unequal-randomisation study. The compact public package retains allocation/evidence-planning primitives but not the entire historical Monte Carlo portfolio-risk engine.

Accordingly, this file is methodological context rather than a current-workflow regression target or production recommendation.

## Reproduce the current reference

```bash
make reference
make validate
```

See `docs/REPRODUCIBILITY.md` for the provenance rule used throughout the repository.
