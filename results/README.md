# Reference and planning results

This directory contains two evidence classes.

## `reference_summary.csv`

A pinned summary of the current **v0.26** deterministic reference run (`seed=2206`, `days=120`). The current workflow adds processing-time and watermark evidence while preserving the v0.25 commercial, DAU and mature-retention truth.

The authoritative full build is the generated `reference-evidence` GitHub Actions artifact. It contains the full CSV/JSON evidence set, `workbench.duckdb`, and `MANIFEST.json`.

The v0.26 reference distinguishes:

- event time (`event_ts`) from processing time (`ingested_at`);
- provisional dates from dates nominally final under the 48-hour watermark;
- late events from the smaller subset that actually revise a KPI cell;
- mature retention users from users excluded because D7/D30 has not matured yet.

The verified reference contains 1,367 events arriving more than 48 hours late (0.496% of certified rows). At the 2026-04-30 processing snapshot, 24 not-yet-ingested events belong to event dates already behind the watermark, and their later settlement changes eight product-date-metric cells.

The 48-hour watermark is a reference policy rather than a claim of an optimal SLA.

## Processing-time evidence

The generated reference includes:

```text
late_arrival_contract.json
late_arrival_summary.csv
watermark_late_events.csv
watermark_metric_revisions.csv
watermark_revision_summary.csv
```

`watermark_late_events.csv` is row-level exception evidence. `watermark_metric_revisions.csv` compares point-in-time and settled KPI cells so a late row is not automatically equated with business impact.

## Retention maturity evidence

Retention remains point-in-time. Only cohorts whose target date is on or before the declared `analysis_as_of` enter D7/D30 denominators. The maturity outputs show eligible and excluded users explicitly rather than treating immature cohorts as churn.

## `risk_aware_design.csv`

A preserved planning snapshot from the broader pre-v0.23 unequal-randomisation study. The compact public package retains allocation/evidence-planning primitives but not the entire historical Monte Carlo portfolio-risk engine.

Accordingly, this file is methodological context rather than a current-workflow regression target or production recommendation.

## Reproduce the current reference

```bash
make reference
make validate
```

See `docs/REPRODUCIBILITY.md` for the provenance rule and `docs/LATE_ARRIVAL_GOVERNANCE.md` for the processing-time contract.
