# Reference and planning results

This directory contains current deterministic reference evidence plus preserved historical planning context.

## `reference_summary.csv`

A pinned summary of the current **v0.29** deterministic reference (`seed=2206`, `days=120`). The current freshness evidence deliberately reports three different decision strengths:

```text
48h = Apr-30 point-in-time local optimum
96h = observed 9/9 rolling-stable policy
none = family-wise 95% statistically certified policy under v0.29
```

The authoritative full build is the generated `reference-evidence` GitHub Actions artifact. It contains the CSV/JSON evidence set, `workbench.duckdb`, and `MANIFEST.json`.

## Point-in-time calibration

For each 24/48/72/96-hour candidate, the late-event decision denominator contains only events whose event date is on or before that candidate's watermark date. At the final 2026-04-30 snapshot, 48h is the shortest candidate satisfying all four point-estimate hard constraints.

## Rolling observed stability

The same candidate grid and unchanged risk budget are replayed across nine weekly snapshots.

| Candidate | Observed feasible windows | Observed stable? |
|---|---:|---|
| 24h | 0 / 9 | No |
| 48h | 5 / 9 | No |
| 72h | 8 / 9 | No |
| 96h | **9 / 9** | **Yes** |

The per-window shortest-feasible sequence is `72,72,72,96,48,48,48,48,48` hours. Under the declared all-window point-estimate rule, 96h is the observed-stable policy.

## v0.29 uncertainty certification

v0.29 adds one-sided exact Clopper–Pearson upper bounds to the late-event and revised-KPI-cell proportions. Because selection considers four candidates across nine windows and two proportional constraints, the full family contains **72 simultaneous bounds**. A 95% family-wise Bonferroni correction uses per-bound alpha `0.05 / 72 = 0.0006944444...`.

| Candidate | Observed feasible windows | Certified windows | Worst late upper | Worst revised-cell upper |
|---|---:|---:|---:|---:|
| 24h | 0 / 9 | **0 / 9** | 7.1543% | 4.5588% |
| 48h | 5 / 9 | **0 / 9** | 0.5601% | 3.5722% |
| 72h | 8 / 9 | **0 / 9** | 0.5612% | 2.4904% |
| 96h | 9 / 9 | **0 / 9** | **0.5485%** | **1.7385%** |

The 96h point estimates are observed feasible in every window, but the simultaneous upper bounds exceed the 0.50% late-event and 1.00% revised-cell budgets. The statistical decision is therefore:

```text
status = no_candidate_certified_familywise_95
selected_lateness_hours = null
```

This is an insufficient-evidence result, not proof that the 96h policy is unsafe.

Maximum revenue and paid-subscription revisions remain deterministic hard gates; v0.29 does not fabricate confidence intervals for extreme-value statistics without a defensible tail model.

Generated uncertainty evidence:

```text
watermark_uncertainty_grid.csv
watermark_uncertainty_summary.csv
watermark_uncertainty_contract.json
watermark_certification_decision.json
```

## Earlier processing-time and retention evidence

The row-level/metric-level late-arrival audit remains part of the current build, including late-event exceptions, settled-vs-snapshot KPI revisions and idempotent keyed backfill evidence. Retention also remains point-in-time: only cohorts whose target date is on or before `analysis_as_of` enter D7/D30 denominators.

## `risk_aware_design.csv`

A preserved planning snapshot from the broader pre-v0.23 unequal-randomisation study. It is methodological context rather than a current-workflow regression target or production recommendation.

## Reproduce the current reference

```bash
make check
```

or run validators separately:

```bash
make reference
python scripts/validate_build.py build/reference
python scripts/validate_watermark_backtest.py build/reference
python scripts/validate_uncertainty_certification.py build/reference
python scripts/validate_reference_claims.py build/reference
```

See `docs/WATERMARK_CALIBRATION.md`, `docs/WATERMARK_STABILITY.md`, `docs/WATERMARK_UNCERTAINTY.md`, `docs/LATE_ARRIVAL_GOVERNANCE.md`, and `docs/REPRODUCIBILITY.md`.
