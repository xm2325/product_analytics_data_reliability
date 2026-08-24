# Product Analytics & Data Reliability Workbench

**Version:** v0.33  
**Stack:** Python · DuckDB · SQL · Pandas · NumPy · SciPy · Statsmodels · Pytest · GitHub Actions

A reproducible analytics workbench for a synthetic portfolio of subscription products. It is organised around one practical question:

> When a product KPI moves, can the team trust the number, explain the movement, test a product change, and make a defensible business decision using only evidence that is actually available?

The repository connects four layers that are often demonstrated separately:

```text
data correctness
    ↓
metric / point-in-time correctness
    ↓
experiment validity + uncertainty + guardrails
    ↓
decision-aware business impact planning
```

It also includes forecast gates, processing-time freshness, watermark calibration, rolling SLA backtesting, uncertainty-aware certification, prospective evidence planning and SHA-256 evidence provenance.

All data and results are synthetic, controlled-fault outputs or explicitly labelled planning studies. Nothing here is presented as production-company performance, customer scale or realised business impact.

## Headline reference

The deterministic reference uses `seed=2206`, `days=120`.

| Check | Reference result |
|---|---:|
| Raw events | **276,249** |
| Rejected / certified rows | **589 / 275,660** |
| Forecast metrics approved / withheld | **3 / 6** |
| Pricing experiment users | **8,000** |
| Pricing experiment action | **HOLD** |
| Conditional paid-guardrail target | **6,393 users / arm** |
| Current experiment arm size | **4,000 users / arm** |
| Counterfactual treated users in launch scenario | **150,000** |
| Counterfactual 30d cohort revenue impact | **£102,762** |
| Decision-authorised treated users | **0** |
| Apr-30 point-in-time SLA | **48h** |
| Observed rolling-stable SLA | **96h** |
| Family-wise certified SLA | **none** |
| v0.33 unit tests | **68 passed** |
| Portable artifacts in reference manifest | **44** |

The central v0.33 result is deliberately not “positive experiment ⇒ ship”. Revenue evidence is positive, but the paid-conversion guardrail remains unresolved, so positive business impact is kept **counterfactual-only**.

## v0.33: counterfactual impact is not authorised impact

The v0.32 pricing experiment remains unchanged:

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

v0.33 adds two downstream planning questions without changing that decision.

### 1. What additional evidence would clear the paid guardrail if current rates persisted?

The paid-conversion CI uses the same `ddof=1` difference-in-proportions variance convention as the experiment. Under the explicit assumption that the observed control/treatment conversion rates remain representative, the first equal-allocation arm size whose projected 95% lower bound is strictly above -3pp is:

```text
current arm size          = 4,000
conditional target        = 6,393 / arm
conditional increment     = 2,393 / arm
```

The integer boundary is audited directly: 6,393 passes the projected rule and 6,392 does not.

This is **not** a power guarantee. Future arm rates can move. If the point estimate itself were at or below -3pp, the planner returns a structural point-estimate failure rather than claiming more sample can repair the result.

### 2. What would the validated 30-day revenue effect imply under a synthetic launch ramp?

The counterfactual scenario contains three 100,000-user eligible cohorts entering over 90 calendar days with hypothetical adoption shares of 25%, 50% and 75%:

| Cohort | Eligible users | Hypothetical adoption | Hypothetical treated users |
|---|---:|---:|---:|
| 1 | 100,000 | 25% | 25,000 |
| 2 | 100,000 | 50% | 50,000 |
| 3 | 100,000 | 75% | 75,000 |
| **Total** | **300,000** | — | **150,000** |

Each cohort contributes only its own first 30-day outcome. The project does **not** multiply a 30-day effect by three and does not claim 90-day LTV persistence.

Fixed-volume effect propagation gives:

```text
counterfactual incremental revenue  = £102,762.12
95% interval                        = [£82,714.46, £122,809.79]
```

The experiment decision is then applied separately:

```text
experiment action                  = HOLD
planning status                    = counterfactual_only
decision-authorised rollout        = false
authorised treated users           = 0
authorised incremental revenue     = null
```

So the project can say “this effect would be economically meaningful under the stated synthetic scenario” without saying “ship it”. That distinction is enforced in code, artifacts and CI.

Generated v0.33 evidence:

```text
pricing_impact_scenario.csv
pricing_impact_contract.json
pricing_guardrail_evidence_plan.json
pricing_impact_decision.json
```

`scripts/validate_impact_plan.py` independently reloads the experiment evidence and checks the current paid-conversion CI, the 6,393/6,392 target boundary, launch-ramp volumes, revenue scaling, and `HOLD → counterfactual_only → zero authorised exposure`.

See [`docs/IMPACT_PLANNING.md`](docs/IMPACT_PLANNING.md).

## v0.32: decision-grade pricing experiment

The controlled pricing reference contains exactly 4,000 control and 4,000 treatment users.

Before treatment effects can drive a decision, assignment integrity must pass an exact two-sided binomial sample-ratio-mismatch test with expected treatment share 0.5 and `alpha = 0.001`.

The primary metric is 30-day revenue. It is estimated with ANCOVA using pre-period 30-day revenue as a covariate and HC3 heteroskedasticity-robust standard errors. The primary gate requires the lower bound of a 95% two-sided confidence interval to be positive.

The guardrail is 30-day paid conversion. Its treatment-control difference uses a 95% two-sided confidence interval with a pre-specified non-inferiority margin of **-3 percentage points**. Revenue cannot compensate for a failed paid-conversion guardrail.

The HOLD result is intentional. The paid-conversion point estimate is inside the allowed harm margin, but its lower confidence bound crosses -3 percentage points. The experiment therefore does not have enough evidence to clear the guardrail even though the revenue result is strongly positive.

Generated evidence:

```text
pricing_experiment_users.csv
pricing_experiment_estimates.csv
pricing_experiment_contract.json
pricing_experiment_decision.json
```

`scripts/validate_pricing_experiment.py` reloads the user-level artifact and independently recomputes assignment balance, SRM, ANCOVA + HC3 revenue uncertainty, paid-conversion uncertainty and the final gate state.

See [`docs/EXPERIMENT_DECISIONING.md`](docs/EXPERIMENT_DECISIONING.md).

## Freshness evidence ladder

Freshness decisions are deliberately separated into four evidence levels:

```text
48h   = shortest feasible candidate at the final 2026-04-30 snapshot
96h   = shortest candidate observed feasible in all 9 rolling windows
none  = candidate certified at 95% family-wise confidence
96h   = only candidate whose current certification gap is evidence-depth-only
```

These statements are not interchangeable. A policy can look feasible at one snapshot, remain feasible across observed windows, and still lack enough information for a simultaneous confidence claim.

## Hard watermark risk budget

The same four constraints are carried through calibration, rolling backtesting, uncertainty analysis and evidence planning:

```text
late-event fraction among finalizable events <= 0.50%
revised finalized KPI-cell fraction          <= 1.00%
max |single revenue revision|                 <= £10
max |paid-subscription revision|              <= 1
```

There is no weighted score and no post-hoc relaxation. A revenue hard-gate breach cannot be compensated by a lower late-event rate.

## Cycle-stable certification evidence targets

The prospective count is

```text
x = ceil(planning_rate × n)
```

so adverse counts change in discrete jumps. v0.31 therefore does not report a single passing `n` as a global threshold. It finds a passing point and audits the next full `ceil(1 / planning_rate)` count-jump cycle.

The machine-readable contract records:

```text
global_monotonic_threshold_claimed = false
```

A shared `count_jump_cycle_trials()` function is used by generator and validator. Reciprocal boundaries are normalised to the nearest integer only within **8 ULPs**, preventing CSV/pandas round-trips from turning true boundaries such as 135 or 333 into 136 or 334 while preserving conservative ceilings for genuine near-integers.

| Candidate | Main problem / target | Audited cycle | Evidence-only addressable? |
|---|---|---:|---:|
| 24h | late 6.95%, revised cells 1.94%, max revenue £23.98 | — | **No** |
| 48h | late target 99,573,018; revised cells 1.29%, max revenue £11.99 | 201 late-event positions | **No** |
| 72h | late target >100M search cap; revised target 14,989; max revenue £11.99 | 135 revised-cell positions | **No** |
| 96h | late target 2,733,153; revised target 2,011; hard gates pass | 206 / 333 | **Yes** |

For 96h:

```text
required finalizable-event trials   = 2,733,153
required finalized KPI cells        = 2,011
late-event audited cycle             = 206
revised-cell audited cycle           = 333
late-event-bound evidence depth      = 1,330 days
revised-cell-bound evidence depth    = 224 days
combined planning depth              = 1,330 days (~3.64 years)
```

**The 1,330-day value is not a promise that waiting 1,330 additional calendar days will certify 96h.** It conditions on future risk rates, throughput and the statistical model remaining at the stated planning values.

See [`docs/CERTIFICATION_EVIDENCE_PLANNING.md`](docs/CERTIFICATION_EVIDENCE_PLANNING.md).

## Observed stability is not statistical certification

For each candidate-window row, one-sided exact Clopper–Pearson upper confidence bounds are added for late-event and revised-KPI-cell proportions. The selection family contains 72 simultaneous one-sided bounds. A 95% family-wise Bonferroni correction gives `per_bound_alpha = 0.05 / 72`.

| Candidate | Observed feasible windows | Certified windows | Worst late upper | Worst revised-cell upper |
|---|---:|---:|---:|---:|
| 24h | 0 / 9 | **0 / 9** | 7.154% | 4.559% |
| 48h | 5 / 9 | **0 / 9** | 0.560% | 3.572% |
| 72h | 8 / 9 | **0 / 9** | 0.561% | 2.490% |
| 96h | 9 / 9 | **0 / 9** | 0.549% | 1.739% |

Therefore:

```text
status = no_candidate_certified_familywise_95
selected_lateness_hours = null
budget_relaxed_after_uncertainty = false
weighted_score_used = false
```

This does not establish that 96h is unsafe. It says current evidence is insufficient for the declared simultaneous certification claim.

See [`docs/WATERMARK_UNCERTAINTY.md`](docs/WATERMARK_UNCERTAINTY.md).

## Rolling stability

Nine weekly processing snapshots from 2026-03-05 through 2026-04-30 produce the per-window shortest-feasible sequence:

```text
72h, 72h, 72h, 96h, 48h, 48h, 48h, 48h, 48h
```

Observed feasibility:

| Candidate | Feasible windows | Rate |
|---|---:|---:|
| 24h | 0 / 9 | 0.0% |
| 48h | 5 / 9 | 55.6% |
| 72h | 8 / 9 | 88.9% |
| 96h | **9 / 9** | **100%** |

Under the observed all-window rule, 96h is the shortest stable candidate. At the final Apr-30 snapshot alone, 48h remains the shortest feasible candidate.

## Point-in-time metric governance

Earlier evidence contracts remain active:

- **Retention maturity:** only cohorts whose D7/D30 target date is observable by `analysis_as_of` enter the denominator; immature cohorts remain explicit exclusions rather than churn.
- **DAU semantics:** current DAU uses explicit `app_open`; the deprecated any-event definition overstates mean DAU by 2.21%–5.27% in the reference data.
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
  -> independent SRM, effect, uncertainty and experiment-decision recomputation

validate_impact_plan.py
  -> independent guardrail evidence target, cohort impact and authorisation recomputation

validate_reference_claims.py
  -> pinned seed=2206, days=120 headline numerical claims

validate_static_claim_ledger.py
  -> checked-in public claim ledger must agree with generated evidence
```

The experiment and impact validators recompute from lower-level evidence rather than trusting generated summary artifacts. A method or data change that moves a published boundary must fail a claim gate until the public evidence is reviewed and updated.

## Quick start

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -e .
make check
```

## Reproducibility boundary

Current numerical claims must either be regenerated by the present workflow and checked in CI or explicitly labelled as preserved historical context. The ingestion-delay process, candidate grid, risk budgets, pricing experiment and launch-cohort scale are synthetic/reference assumptions, not estimates of any real company's infrastructure or customers.

The watermark binomial uncertainty layer treats event/cell indicators as Bernoulli observations; batch-, source- and day-level dependence is not yet included. Prospective watermark sample-size calculations condition on observed planning rates remaining representative.

The pricing experiment is fixed-horizon. Sequential monitoring, repeated peeking, network interference and cross-experiment interaction are outside the current claim. v0.33 impact planning does not assume effect persistence beyond 30 days and does not model acquisition-mix shifts, saturation, refunds, platform fees or contribution margin.

See [`docs/IMPACT_PLANNING.md`](docs/IMPACT_PLANNING.md), [`docs/EXPERIMENT_DECISIONING.md`](docs/EXPERIMENT_DECISIONING.md), [`docs/LATE_ARRIVAL_GOVERNANCE.md`](docs/LATE_ARRIVAL_GOVERNANCE.md), [`docs/WATERMARK_CALIBRATION.md`](docs/WATERMARK_CALIBRATION.md), [`docs/WATERMARK_STABILITY.md`](docs/WATERMARK_STABILITY.md), [`docs/WATERMARK_UNCERTAINTY.md`](docs/WATERMARK_UNCERTAINTY.md), [`docs/CERTIFICATION_EVIDENCE_PLANNING.md`](docs/CERTIFICATION_EVIDENCE_PLANNING.md) and [`docs/REPRODUCIBILITY.md`](docs/REPRODUCIBILITY.md).