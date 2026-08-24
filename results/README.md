# Reference and planning results

This directory contains current deterministic reference evidence plus preserved historical planning context.

## Current deterministic reference

The current reference is **v0.30** with `seed=2206`, `days=120`. Freshness evidence is intentionally separated into four decision strengths:

```text
48h  = Apr-30 shortest point-in-time feasible candidate
96h  = shortest candidate observed feasible in all 9 rolling windows
none = family-wise 95% statistically certified candidate under v0.29/v0.30
96h  = only candidate whose remaining gap is evidence-depth-only under v0.30 planning
```

The authoritative full build is the generated `reference-evidence` GitHub Actions artifact. It contains CSV/JSON evidence, `workbench.duckdb`, and `MANIFEST.json`.

## v0.30 certification evidence plan

The unchanged risk budget and the unchanged 72-bound family are carried forward from v0.29. v0.30 asks whether each candidate can plausibly be repaired by more proportional evidence without changing either contract.

| Candidate | Planning classification | Key evidence |
|---|---|---|
| 24h | not evidence-only | late/revised rates and £23.98 revenue maximum already breach budgets |
| 48h | not evidence-only | revised-cell rate 1.288% and £11.99 revenue maximum breach budgets |
| 72h | not evidence-only | £11.99 revenue maximum breach; late requirement exceeds 100M search cap |
| 96h | **evidence-depth-only** | point rates and deterministic maxima pass |

For 96h:

```text
required finalizable-event trials  = 2,718,757
required finalized KPI cells       = 1,853
estimated late-bound depth          = 1,323 days
estimated revised-cell depth        = 206 days
combined planning depth             = 1,323 days (~3.62 years)
```

These are **total prospective evidence-depth estimates under fixed planning rates and throughput**, not a guarantee that waiting that many additional wall-clock days will certify the policy.

Generated v0.30 artifacts:

```text
watermark_evidence_plan.csv
watermark_evidence_plan_contract.json
watermark_evidence_plan_decision.json
```

## Point-in-time and rolling evidence

For each 24/48/72/96-hour candidate, the late-event decision denominator contains only events whose event date is on or before that candidate's watermark. At the final 2026-04-30 snapshot, 48h is the shortest point-estimate feasible candidate.

Across nine weekly snapshots:

| Candidate | Observed feasible windows | Observed stable? |
|---|---:|---|
| 24h | 0 / 9 | No |
| 48h | 5 / 9 | No |
| 72h | 8 / 9 | No |
| 96h | **9 / 9** | **Yes** |

The per-window shortest-feasible sequence is `72,72,72,96,48,48,48,48,48` hours.

## Uncertainty certification

The uncertainty layer uses one-sided exact Clopper–Pearson upper bounds for the late-event and revised-KPI-cell proportions. Four candidates × nine windows × two proportional constraints gives **72 simultaneous bounds** under a 95% family-wise Bonferroni correction.

| Candidate | Certified windows | Worst late upper | Worst revised-cell upper |
|---|---:|---:|---:|
| 24h | 0 / 9 | 7.1543% | 4.5588% |
| 48h | 0 / 9 | 0.5601% | 3.5722% |
| 72h | 0 / 9 | 0.5612% | 2.4904% |
| 96h | **0 / 9** | **0.5485%** | **1.7385%** |

The family-wise decision remains:

```text
status = no_candidate_certified_familywise_95
selected_lateness_hours = null
```

This is an insufficient-evidence result, not evidence that 96h is unsafe. Maximum revenue and paid-subscription revisions remain deterministic hard gates rather than receiving invented confidence intervals.

## Earlier processing-time and retention evidence

The row-level/metric-level late-arrival audit remains part of the current build, including late-event exceptions, settled-vs-snapshot KPI revisions and idempotent keyed backfill evidence. Retention also remains point-in-time: only cohorts whose target date is on or before `analysis_as_of` enter D7/D30 denominators.

## Preserved historical context

`risk_aware_design.csv` is a preserved pre-v0.23 planning snapshot from a broader unequal-randomisation study. It is methodological context rather than a current-workflow regression target or production recommendation.

## Reproduce the current reference

```bash
make check
```

or run the gates separately:

```bash
make reference
python scripts/validate_build.py build/reference
python scripts/validate_watermark_backtest.py build/reference
python scripts/validate_uncertainty_certification.py build/reference
python scripts/validate_evidence_plan.py build/reference
python scripts/validate_reference_claims.py build/reference
```

See `docs/WATERMARK_CALIBRATION.md`, `docs/WATERMARK_STABILITY.md`, `docs/WATERMARK_UNCERTAINTY.md`, `docs/CERTIFICATION_EVIDENCE_PLANNING.md`, `docs/LATE_ARRIVAL_GOVERNANCE.md`, and `docs/REPRODUCIBILITY.md`.
