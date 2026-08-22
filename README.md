# Product Analytics & Data Reliability Workbench

**Version:** v0.29  
**Stack:** Python · DuckDB · SQL · Pandas · NumPy · SciPy · Statsmodels · Pytest · GitHub Actions

A reproducible analytics workbench for a synthetic portfolio of subscription products. It is organised around one practical question:

> When a product KPI moves, can the team trust the number, explain the movement, and make a defensible decision using only evidence actually available at the reporting time?

The repository combines event certification, metric contracts, revenue reconciliation, point-in-time retention, forecast gates, experiment guardrails, processing-time freshness, watermark calibration, rolling SLA backtesting, uncertainty-aware certification and evidence provenance in one auditable workflow.

All data and results are synthetic, controlled-fault outputs or explicitly labelled planning stress tests. Nothing here is presented as production-company performance.

## v0.29 reference result: observed stability is not statistical certification

The deterministic reference uses `seed=2206`, `days=120`. The core freshness results now have three distinct evidence levels:

```text
48h  = shortest feasible candidate at the final 2026-04-30 snapshot
96h  = shortest candidate observed feasible in all 9 rolling windows
none = candidate certified at 95% family-wise confidence under the v0.29 model
```

That last result is deliberate. v0.28 found 96h feasible in 9/9 windows, but v0.29 refuses to convert a point-estimate backtest into a confidence claim without accounting for uncertainty and multiple comparisons.

| Check | Reference result |
|---|---:|
| Raw events | **276,249** |
| Rejected / certified rows | **589 / 275,660** |
| Apr-30 point-in-time SLA | **48h** |
| Observed rolling-stable SLA | **96h** |
| Family-wise certified SLA | **none** |
| Rolling windows | **9** |
| Candidate-window rows | **36** |
| Simultaneous one-sided proportion bounds | **72** |
| Family-wise confidence | **95%** |
| Unit + parity/calibration/backtest/uncertainty tests | **47 passed** in first v0.29 CI build |
| Portable artifacts in SHA-256 manifest | **33** |

The first v0.29 CI build passed the unit suite, reference build, generic validator, rolling-backtest validator and uncertainty-certification validator. Its only failure was the old v0.28 pinned version claim; that gate is now rewritten to pin the v0.29 negative certification result and must pass on the final branch head before merge.

## Existing hard risk budget remains unchanged

```text
late-event fraction among finalizable events <= 0.50%
revised finalized KPI-cell fraction          <= 1.00%
max |single revenue revision|                 <= £10
max |paid-subscription revision|              <= 1
```

There is no weighted score. No constraint can compensate for another. The budget is not relaxed after observing either the rolling backtest or the uncertainty analysis.

## v0.28 observed rolling stability

Nine weekly processing snapshots from 2026-03-05 through 2026-04-30 produce the per-window shortest-feasible sequence:

```text
72h, 72h, 72h, 96h, 48h, 48h, 48h, 48h, 48h
```

Observed feasibility:

| Candidate | Feasible windows | Rate | Worst revised-cell fraction | Worst revenue revision |
|---|---:|---:|---:|---:|
| 24h | 0 / 9 | 0.0% | 1.940% | £23.98 |
| 48h | 5 / 9 | 55.6% | 1.288% | £11.99 |
| 72h | 8 / 9 | 88.9% | 0.741% | £11.99 |
| 96h | **9 / 9** | **100%** | 0.300% | £0.00 |

Under the observed all-window rule, 96h is the shortest stable candidate.

## v0.29 simultaneous uncertainty certification

For each candidate-window row, v0.29 adds one-sided exact Clopper–Pearson upper confidence bounds for:

```text
late-event proportion
revised-KPI-cell proportion
```

Because policy selection examines all 4 candidates over all 9 windows and both proportional constraints, the selection family contains:

```text
4 candidates × 9 windows × 2 proportions = 72 one-sided bounds
```

The project uses a **95% family-wise Bonferroni correction**:

```text
family alpha = 0.05
per-bound alpha = 0.05 / 72
                = 0.0006944444...
```

This is intentionally conservative and does not require independence across the overlapping rolling windows for the Bonferroni family-wise guarantee. The individual Clopper–Pearson calculations still rely on a binomial/Bernoulli interpretation within each event or KPI-cell proportion; temporal/batch clustering is explicitly left as a model boundary for the next release.

### Observed vs certified

| Candidate | Observed feasible windows | Certified windows | Worst late point | Worst late upper | Worst revised-cell point | Worst revised-cell upper |
|---|---:|---:|---:|---:|---:|---:|
| 24h | 0 / 9 | **0 / 9** | 6.952% | 7.154% | 1.940% | 4.559% |
| 48h | 5 / 9 | **0 / 9** | 0.4977% | **0.5601%** | 1.288% | **3.572%** |
| 72h | 8 / 9 | **0 / 9** | 0.4999% | **0.5612%** | 0.741% | **2.490%** |
| 96h | 9 / 9 | **0 / 9** | 0.4864% | **0.5485%** | 0.300% | **1.739%** |

The 96h point estimates pass in every window, but its worst simultaneous upper bounds exceed both proportional budgets:

```text
late-event upper bound:   0.5485% > 0.50%
revised-cell upper bound: 1.7385% > 1.00%
```

Therefore the v0.29 certification decision is:

```text
status = no_candidate_certified_familywise_95
selected_lateness_hours = null
budget_relaxed_after_uncertainty = false
weighted_score_used = false
```

This does **not** mean the 96h policy has been shown unsafe. It means the current evidence is insufficient to certify that all relevant proportions satisfy the strict budgets at the declared simultaneous confidence level.

## Why maximum revisions remain hard gates

The maximum observed revenue revision and maximum observed paid-subscription revision are sparse tail statistics. v0.29 does not invent a confidence interval for those maxima without a defensible tail model. They remain deterministic constraints evaluated exactly as in v0.28.

So the uncertainty layer is deliberately asymmetric:

```text
proportions -> one-sided simultaneous statistical upper bounds
maxima       -> observed deterministic hard gates
```

See [`docs/WATERMARK_UNCERTAINTY.md`](docs/WATERMARK_UNCERTAINTY.md).

## Evidence artifacts

The current build adds:

```text
watermark_uncertainty_grid.csv
watermark_uncertainty_summary.csv
watermark_uncertainty_contract.json
watermark_certification_decision.json
```

They sit on top of the existing point-in-time and rolling artifacts:

```text
watermark_policy_grid.csv
watermark_policy_decision.json
watermark_rolling_grid.csv
watermark_rolling_windows.csv
watermark_stability_summary.csv
watermark_stability_decision.json
```

## Validation layers

```text
pytest
  -> implementation behaviour and SQL/Python parity

validate_build.py
  -> generic reference-build invariants

validate_watermark_backtest.py
  -> point-in-time and rolling selection accounting

validate_uncertainty_certification.py
  -> simultaneous-bound accounting and certification rules

validate_reference_claims.py
  -> pinned seed=2206, days=120 public claims
```

The v0.29 pinned gate preserves all three current conclusions simultaneously: Apr-30 selects 48h; observed rolling stability selects 96h; statistical certification selects no candidate. If a later method or dataset changes any of these, the public claim must be reviewed rather than drifting silently.

## Point-in-time retention, forecast governance and data reliability

The earlier evidence contracts remain active. Retention includes only cohorts whose D7/D30 target date has matured by `analysis_as_of`; future outcomes do not leak into denominators. DAU uses explicit `app_open` activity rather than any-event activity. Forecasts are gated by holdout performance: all three DAU seasonal-naive baselines pass at roughly 3.9%–5.9% MAPE while all six revenue/subscription baselines remain withheld at roughly 25.6%–37.3% MAPE.

The row-level processing-time audit remains reproducible: late events are preserved, reconciled and applied through idempotent keyed backfill rather than silently discarded after a nominal finalization decision.

## Quick start

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -e .
make check
```

The complete gate runs tests, reference generation, generic validation, watermark-backtest validation, uncertainty-certification validation and pinned-reference validation.

## Reproducibility boundary

Current numerical claims must either be regenerated by the present workflow and checked in CI or explicitly labelled as preserved historical context. The ingestion-delay process, risk budgets and candidate grid are synthetic/reference assumptions, not estimates of any real company's infrastructure.

The Clopper–Pearson layer treats the event/cell indicators within each proportion as Bernoulli observations. v0.29 does not yet model batch-, source- or day-level dependence. A natural next step is cluster-aware/block-bootstrap certification, and that method must be allowed to confirm or overturn the current `no_candidate_certified` result.

See [`docs/LATE_ARRIVAL_GOVERNANCE.md`](docs/LATE_ARRIVAL_GOVERNANCE.md), [`docs/WATERMARK_CALIBRATION.md`](docs/WATERMARK_CALIBRATION.md), [`docs/WATERMARK_STABILITY.md`](docs/WATERMARK_STABILITY.md), [`docs/WATERMARK_UNCERTAINTY.md`](docs/WATERMARK_UNCERTAINTY.md) and [`docs/REPRODUCIBILITY.md`](docs/REPRODUCIBILITY.md).
