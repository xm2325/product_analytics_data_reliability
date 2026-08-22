# Reference and planning results

This directory contains current deterministic reference evidence plus preserved historical planning context.

## `reference_summary.csv`

A pinned summary of the current **v0.28** deterministic reference (`seed=2206`, `days=120`). v0.28 preserves the commercial and metric truth of the earlier reference but tightens the watermark decision scope and adds a nine-window rolling SLA backtest.

The authoritative full build is the generated `reference-evidence` GitHub Actions artifact. It contains the full CSV/JSON evidence set, `workbench.duckdb`, and `MANIFEST.json`.

## Point-in-time calibration evidence

For each 24/48/72/96-hour candidate, the SLA late-event denominator now contains only events whose event date is on or before that candidate's watermark date. The whole settled-stream late rate remains diagnostic only.

At the final 2026-04-30 processing snapshot:

| Candidate | Point-in-time late-event fraction | Late events still missing from nominally-final dates | Revised KPI-cell fraction | Feasible? |
|---|---:|---:|---:|---|
| 24h | **6.932%** | 62 | **1.214%** | No |
| 48h | **0.4951%** | 24 | **0.753%** | Yes |
| 72h | **0.4944%** | 11 | **0.380%** | Yes |
| 96h | **0.4814%** | 0 | **0.000%** | Yes |

The local Apr-30 selector therefore still chooses **48h** as the shortest feasible candidate.

Generated evidence:

```text
watermark_policy_grid.csv
watermark_policy_decision.json
```

## Rolling stability evidence

The same candidate grid and unchanged hard budget are replayed over nine weekly processing snapshots.

| Candidate | Feasible windows | Feasibility rate | Stable in every window? |
|---|---:|---:|---|
| 24h | 0 / 9 | 0.0% | No |
| 48h | 5 / 9 | 55.6% | No |
| 72h | 8 / 9 | 88.9% | No |
| 96h | **9 / 9** | **100%** | **Yes** |

The per-window shortest selection sequence is:

```text
72h, 72h, 72h, 96h, 48h, 48h, 48h, 48h, 48h
```

The strict stability selector chooses the shortest candidate feasible in **every** window, so the current robust reference policy is **96h**. The budget is not relaxed after seeing the result and no weighted score is used.

Generated evidence:

```text
watermark_rolling_grid.csv
watermark_rolling_windows.csv
watermark_stability_summary.csv
watermark_stability_decision.json
```

The distinction between the two decisions is intentional:

```text
48h = final-snapshot local optimum
96h = rolling all-window stable SLA
```

## Processing-time audit evidence

The row-level/metric-level late-arrival audit remains part of the current build:

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

A preserved planning snapshot from the broader pre-v0.23 unequal-randomisation study. It is methodological context rather than a current-workflow regression target or production recommendation.

## Reproduce the current reference

```bash
make check
```

or run the validators separately:

```bash
make reference
python scripts/validate_build.py build/reference
python scripts/validate_watermark_backtest.py build/reference
python scripts/validate_reference_claims.py build/reference
```

See `docs/REPRODUCIBILITY.md`, `docs/LATE_ARRIVAL_GOVERNANCE.md`, `docs/WATERMARK_CALIBRATION.md`, and `docs/WATERMARK_STABILITY.md` for evidence contracts and interpretation boundaries.
