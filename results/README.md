# Reference and planning results

This directory contains two evidence classes.

## `reference_summary.csv`

A pinned summary of the current **v0.27** deterministic reference run (`seed=2206`, `days=120`). v0.27 preserves the v0.26 processing-time audit and adds a transparent finalization-SLA calibration over 24/48/72/96-hour watermark candidates.

The authoritative full build is the generated `reference-evidence` GitHub Actions artifact. It contains the full CSV/JSON evidence set, `workbench.duckdb`, and `MANIFEST.json`.

The current reference distinguishes:

- event time (`event_ts`) from processing time (`ingested_at`);
- mature retention users from users whose D7/D30 horizon is not yet observable;
- late rows from the smaller subset that actually revises a KPI cell;
- a fixed watermark audit from a multi-candidate SLA decision.

## Watermark calibration evidence

The candidate policies are replayed against the same event stream and the same 2026-04-30 processing snapshot.

| Candidate | Late-event fraction | Late events still missing from nominally-final dates | Revised KPI-cell fraction | Feasible? |
|---|---:|---:|---:|---|
| 24h | **6.958%** | 62 | **1.214%** | No |
| 48h | **0.496%** | 24 | **0.753%** | Yes |
| 72h | **0.496%** | 11 | **0.380%** | Yes |
| 96h | **0.482%** | 0 | **0.000%** | Yes |

The reference budget requires late events <=0.50%, revised finalized KPI cells <=1.00%, maximum absolute revenue revision <=£10, and maximum absolute paid-subscription revision <=1. The selector uses no weighted score: it chooses the **shortest candidate satisfying every hard constraint**. The resulting reference SLA is **48 hours**.

Generated decision evidence:

```text
watermark_policy_grid.csv
watermark_policy_decision.json
```

The CI path contains both a generic validator and a pinned deterministic-reference validator. If a future code/data change makes 24h feasible or 48h infeasible, the public 48h claim must be reviewed rather than silently drifting.

## Processing-time audit evidence

The v0.26 row-level/metric-level audit remains part of the current build:

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
python scripts/validate_reference_claims.py build/reference
```

See `docs/REPRODUCIBILITY.md`, `docs/LATE_ARRIVAL_GOVERNANCE.md`, and `docs/WATERMARK_CALIBRATION.md` for the evidence contracts and interpretation boundaries.
