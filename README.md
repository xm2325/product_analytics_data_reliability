# Product Analytics & Data Reliability Workbench

**Version:** v0.32  
**Stack:** Python · DuckDB · SQL · Pandas · NumPy · SciPy · Statsmodels · Pytest · GitHub Actions

A reproducible analytics workbench for a synthetic portfolio of subscription products. It is organised around one practical question:

> When a product KPI moves, can the team trust the number, explain the movement, and make a defensible decision using only evidence actually available at the reporting time?

The repository combines event certification, metric contracts, revenue reconciliation, point-in-time retention, forecast gates, decision-grade experiment guardrails, processing-time freshness, watermark calibration, rolling SLA backtesting, uncertainty-aware certification, prospective evidence planning and evidence provenance in one auditable workflow.

All data and results are synthetic, controlled-fault outputs or explicitly labelled planning studies. Nothing here is presented as production-company performance.

## Verified evidence ladder

The deterministic reference uses `seed=2206`, `days=120`. Freshness decisions are deliberately separated into four evidence levels:

```text
48h   = shortest feasible candidate at the final 2026-04-30 snapshot
96h   = shortest candidate observed feasible in all 9 rolling windows
none  = candidate certified at 95% family-wise confidence
96h   = only candidate whose current certification gap is evidence-depth-only
```

These statements are not interchangeable. A policy can look feasible at one snapshot, remain feasible across observed windows, and still lack enough information for a simultaneous confidence claim.

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
| Pricing experiment users | **8,000** |
| Pricing experiment action | **HOLD** |
| v0.32 unit tests | **63 passed** |
| Portable artifacts in the reference manifest | **40** |

## v0.32: decision-grade pricing experiment

v0.32 extends the workbench from “can we trust the metric?” to “can we make a reproducible product decision from the metric?”. The controlled pricing reference contains exactly 4,000 control and 4,000 treatment users.

Before treatment effects can drive a decision, assignment integrity must pass an exact two-sided binomial sample-ratio-mismatch test with expected treatment share 0.5 and `alpha = 0.001`.

The primary metric is 30-day revenue. It is estimated with ANCOVA using pre-period 30-day revenue as a covariate and HC3 heteroskedasticity-robust standard errors. The primary gate requires the lower bound of a 95% two-sided confidence interval to be positive.

The guardrail is 30-day paid conversion. Its treatment-control difference uses a 95% two-sided confidence interval, with a pre-specified non-inferiority margin of **-3 percentage points**. Revenue cannot compensate for a failed paid-conversion guardrail.

Reference result:

```text
assignment                    4,000 control / 4,000 treatment
SRM p-value                   1.000
revenue effect                +£0.6851 per user over 30 days
revenue 95% CI                [£0.5514, £0.8187]
paid-conversion effect        -1.625 percentage points
paid-conversion 95% CI        [-3.363, +0.113] percentage points
paid harm margin              -3.000 percentage points

assignment_integrity_gate     PASS
revenue_gate                  PASS
paid_guardrail_gate           FAIL
final action                  HOLD
```

The HOLD result is intentional. The paid-conversion point estimate is inside the allowed harm margin, but its lower confidence bound crosses -3 percentage points. The experiment therefore does not have enough evidence to clear the guardrail even though the revenue result is strongly positive.

Generated evidence:

```text
pricing_experiment_users.csv
pricing_experiment_estimates.csv
pricing_experiment_contract.json
pricing_experiment_decision.json
```

`scripts/validate_pricing_experiment.py` reloads the user-level artifact and independently recomputes assignment balance, SRM, ANCOVA + HC3 revenue uncertainty, paid-conversion uncertainty and the final gate state. It also pins the deterministic reference effects, so a method or data change cannot silently move a public experiment claim.

See [`docs/EXPERIMENT_DECISIONING.md`](docs/EXPERIMENT_DECISIONING.md).

## Hard risk budget

The same four constraints are carried through calibration, rolling backtesting, uncertainty analysis and evidence planning:

```text
late-event fraction among finalizable events <= 0.50%
revised finalized KPI-cell fraction          <= 1.00%
max |single revenue revision|                 <= £10
max |paid-subscription revision|              <= 1
```

There is no weighted score and no post-hoc relaxation. A revenue hard-gate breach cannot be compensated by a lower late-event rate.

## v0.31: cycle-stable exact evidence targets

v0.30 asked whether a failed statistical certification could actually be repaired by collecting more evidence. It found that only the 96h candidate was an evidence-depth-only case.

v0.31 fixes a discrete statistical issue in the prospective sample-size calculation. The planning count is

```text
x = ceil(planning_rate × n)
```

so `x` changes in jumps. Near a crossing, one sample size can pass an exact upper-bound limit while a nearby larger sample size fails after the adverse count increments. A single passing `n` is therefore not reported as a threshold.

The v0.31 rule is:

```text
find a passing n
    ↓
compute the count-jump cycle ceil(1 / planning_rate)
    ↓
audit n through n + cycle
    ↓
report n only if every audited position passes
```

The machine-readable contract explicitly records:

```text
global_monotonic_threshold_claimed = false
```

This is a local cycle-stability claim, not a statement that every larger sample size must pass forever.

### Shared float-boundary semantics

The cycle length is computed by one shared `count_jump_cycle_trials()` function used by both the evidence generator and the validator. This prevents CSV/pandas floating-point round-trips from changing an exact reciprocal boundary such as 135 or 333 into 136 or 334.

A reciprocal is normalized to the nearest integer only when it is within **8 floating-point units in the last place (ULPs)**. The two reference round-trip boundaries are 5 ULPs from 135 and 6 ULPs from 333. A genuine near-integer reciprocal such as `135.00000000001` remains outside this budget and therefore retains the conservative ceiling result of 136.

### v0.31 prospective evidence plan

| Candidate | Main problem / target | Audited cycle | Evidence-only addressable? |
|---|---|---:|---:|
| 24h | late 6.95%, revised cells 1.94%, max revenue £23.98 | — | **No** |
| 48h | late target 99,573,018; revised cells 1.29%, max revenue £11.99 | 201 late-event positions | **No** |
| 72h | late target >100M search cap; revised target 14,989; max revenue £11.99 | 135 revised-cell positions | **No** |
| 96h | late target 2,733,153; revised target 2,011; hard gates pass | 206 / 333 | **Yes** |

For the 96-hour candidate:

```text
required finalizable-event trials   = 2,733,153
late-event audited cycle            = 206 trial positions
required finalized KPI cells        = 2,011
revised-cell audited cycle           = 333 trial positions
median event throughput             ~= 2,055.6 / day
median KPI-cell throughput           = 9 / day
late-event-bound evidence depth      = 1,330 days
revised-cell-bound evidence depth    = 224 days
combined planning depth              = 1,330 days (~3.64 years)
```

The late-event proportion remains the planning bottleneck.

The cycle-stable correction changes the v0.30 single-point targets slightly:

| Component | v0.30 | v0.31 cycle-stable |
|---|---:|---:|
| 48h late target | 99,546,369 | **99,573,018** |
| 72h revised-cell target | 14,299 | **14,989** |
| 96h late target | 2,718,757 | **2,733,153** |
| 96h revised-cell target | 1,853 | **2,011** |
| 96h evidence depth | 1,323d | **1,330d** |

The correction does not change the business conclusion, but it prevents a locally passing point from being described as a stronger threshold than the calculation supports.

**The 1,330-day value is not a promise that waiting 1,330 additional calendar days will certify 96h.** It conditions on future risk rates, throughput and the statistical model remaining at the stated planning values.

See [`docs/CERTIFICATION_EVIDENCE_PLANNING.md`](docs/CERTIFICATION_EVIDENCE_PLANNING.md).

## v0.29: observed stability is not statistical certification

For each candidate-window row, the uncertainty layer adds one-sided exact Clopper–Pearson upper confidence bounds for the late-event and revised-KPI-cell proportions.

The selection family contains 72 simultaneous one-sided bounds. A 95% family-wise Bonferroni correction gives `per_bound_alpha = 0.05 / 72`.

| Candidate | Observed feasible windows | Certified windows | Worst late point | Worst late upper | Worst revised-cell point | Worst revised-cell upper |
|---|---:|---:|---:|---:|---:|---:|
| 24h | 0 / 9 | **0 / 9** | 6.952% | 7.154% | 1.940% | 4.559% |
| 48h | 5 / 9 | **0 / 9** | 0.4977% | **0.5601%** | 1.288% | **3.572%** |
| 72h | 8 / 9 | **0 / 9** | 0.4999% | **0.5612%** | 0.741% | **2.490%** |
| 96h | 9 / 9 | **0 / 9** | 0.4864% | **0.5485%** | 0.300% | **1.739%** |

The 96h point estimates pass in every observed window, but its worst simultaneous upper bounds still exceed both proportional budgets. Therefore:

```text
status = no_candidate_certified_familywise_95
selected_lateness_hours = null
budget_relaxed_after_uncertainty = false
weighted_score_used = false
```

This does not establish that 96h is unsafe. It says the current evidence is insufficient for the declared simultaneous certification claim.

Maximum revenue and paid-subscription revisions remain deterministic hard gates; the project does not create confidence intervals for sparse maxima without a stated tail model.

See [`docs/WATERMARK_UNCERTAINTY.md`](docs/WATERMARK_UNCERTAINTY.md).

## v0.28: rolling stability

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

Under the observed all-window rule, 96h is the shortest stable candidate. At the final Apr-30 snapshot alone, however, 48h remains the shortest feasible candidate. Keeping both statements prevents a single as-of date from being mistaken for a robust SLA.

## Point-in-time metric governance

Earlier evidence contracts remain active:

- **Retention maturity:** only cohorts whose D7/D30 target date is observable by `analysis_as_of` enter the denominator; immature cohorts remain explicit exclusions rather than churn.
- **DAU semantics:** v2 DAU uses explicit `app_open`; the deprecated any-event definition overstates mean DAU by 2.21%–5.27% in the reference data.
- **Forecast gating:** all three DAU seasonal-naive baselines pass at about 3.9%–5.9% MAPE; all six revenue/subscription baselines remain withheld at about 25.6%–37.3% MAPE under the unchanged 20% gate.
- **Processing time:** `event_ts` and `ingested_at` are separate; late events are preserved, reconciled and backfilled idempotently rather than silently discarded after nominal finalization.

## Validation layers

```text
pytest
  -> implementation behaviour and Python/DuckDB SQL parity

validate_build.py
  -> generic reference-build invariants

validate_watermark_backtest.py
  -> point-in-time and rolling selection accounting

validate_uncertainty_certification.py
  -> simultaneous-bound accounting and certification rules

validate_evidence_plan.py
  -> cycle-stable evidence-depth vs hard-gate classification

validate_pricing_experiment.py
  -> independent SRM, effect, uncertainty and decision recomputation

validate_reference_claims.py
  -> pinned seed=2206, days=120 public numerical claims
```

The experiment validator recomputes from user-level evidence rather than trusting generated estimate artifacts. The evidence-plan generator and validator share the same count-jump-cycle implementation. A method or data change that moves a published boundary must fail a claim gate until the public evidence is reviewed and updated.

## Quick start

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -e .
make check
```

## Reproducibility boundary

Current numerical claims must either be regenerated by the present workflow and checked in CI or explicitly labelled as preserved historical context. The ingestion-delay process, candidate grid, risk budgets and pricing experiment are synthetic/reference assumptions, not estimates of any real company's infrastructure or customers.

The binomial uncertainty layer for watermark certification treats event/cell indicators as Bernoulli observations. Batch-, source- and day-level dependence is not yet included in that certification model. Prospective sample-size calculations also condition on the observed planning rates remaining representative.

The v0.32 pricing experiment is a fixed-horizon analysis. Its paid-conversion interval uses a large-sample normal approximation in a reference with 4,000 users per arm and event rates away from zero and one. Sequential monitoring, repeated peeking, network interference and cross-experiment interaction are outside the v0.32 claim.

See [`docs/EXPERIMENT_DECISIONING.md`](docs/EXPERIMENT_DECISIONING.md), [`docs/LATE_ARRIVAL_GOVERNANCE.md`](docs/LATE_ARRIVAL_GOVERNANCE.md), [`docs/WATERMARK_CALIBRATION.md`](docs/WATERMARK_CALIBRATION.md), [`docs/WATERMARK_STABILITY.md`](docs/WATERMARK_STABILITY.md), [`docs/WATERMARK_UNCERTAINTY.md`](docs/WATERMARK_UNCERTAINTY.md), [`docs/CERTIFICATION_EVIDENCE_PLANNING.md`](docs/CERTIFICATION_EVIDENCE_PLANNING.md) and [`docs/REPRODUCIBILITY.md`](docs/REPRODUCIBILITY.md).
