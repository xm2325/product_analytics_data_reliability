# Product Analytics & Data Reliability Workbench

**Version:** v0.34  
**Stack:** Python · DuckDB · SQL · Pandas · NumPy · SciPy · Statsmodels · Pytest · GitHub Actions

A reproducible analytics workbench for a synthetic portfolio of subscription products. It is organised around one practical question:

> When a product KPI moves, can the team trust the number, forecast it without future leakage, test a product change, and make a defensible business decision using only evidence that was actually available at the time?

The repository connects five layers that are often demonstrated separately:

```text
data correctness
    ↓
metric / point-in-time correctness
    ↓
forecast eligibility + planning reconciliation
    ↓
experiment validity + uncertainty + guardrails
    ↓
decision-aware business impact planning
```

It also includes processing-time freshness, watermark calibration, rolling SLA backtesting, family-wise uncertainty analysis, prospective evidence planning and SHA-256 evidence provenance.

All data and results are synthetic, controlled-fault outputs or explicitly labelled planning studies. Nothing here is presented as production-company performance, customer scale or realised business impact.

## Headline reference

The deterministic reference uses `seed=2206`, `days=120`.

| Check | Reference result |
|---|---:|
| Raw events | **276,249** |
| Rejected / certified rows | **589 / 275,660** |
| Forecast metrics approved / withheld | **2 / 7** |
| Rolling forecast origins | **4 × 7-day horizons** |
| Forecast backtest points / metric | **28** |
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
| v0.34 unit tests | **75 passed** |
| Portable artifacts in reference manifest | **47** |

The central v0.34 lesson is deliberately stricter than “low forecast error ⇒ use the forecast”. A forecast is eligible for planning only when it has enough leakage-safe backtest evidence, acceptable absolute error, does not lose to a simpler last-value benchmark, and clears the interval-coverage gate.

The experiment side remains equally non-compensatory: positive revenue evidence does not override an unresolved paid-conversion guardrail, so the impact scenario remains **counterfactual-only**.

## v0.34: forecast accuracy is not enough

The previous forecast layer used one terminal 28-point holdout with a weekly seasonal-naive forecast and a 20% MAPE gate. v0.34 keeps the transparent weekly model but upgrades the evidence contract rather than adding a model zoo.

Each product × metric is now evaluated using:

```text
candidate model            = weekly seasonal naive, lag 7
benchmark                  = last observed value carried across the 7-day horizon
rolling origins            = 4
horizon                    = 7 days
backtest points            = 28 per metric
absolute metrics           = MAPE + WAPE
interval                   = 90% symmetric residual interval
interval calibration       = origin-specific; only pre-origin residuals
minimum empirical coverage = 85%
weighted score             = none
future-data leakage        = forbidden
```

Every gate is non-compensatory:

```text
enough backtest evidence
AND absolute accuracy <= limits
AND candidate WAPE <= simple benchmark WAPE
AND interval coverage >= threshold
→ forecast eligible for planning
```

A strong score on one dimension cannot pay for a failure on another.

### Reference forecast decisions

| Metric | Candidate WAPE | Last-value WAPE | 90% interval coverage | Decision |
|---|---:|---:|---:|---|
| `file_transfer:dau` | **5.91%** | 7.05% | 100.0% | **APPROVE** |
| `notes_app:dau` | **3.97%** | 4.64% | 100.0% | **APPROVE** |
| `photo_editor:dau` | 3.92% | **2.56%** | 100.0% | **WITHHOLD** |
| `file_transfer:paid_subscription` | 32.22% | 43.77% | 89.3% | **WITHHOLD** |
| `file_transfer:revenue_gbp` | 32.22% | 43.77% | 89.3% | **WITHHOLD** |
| `notes_app:paid_subscription` | 22.13% | **17.49%** | 92.9% | **WITHHOLD** |
| `notes_app:revenue_gbp` | 22.74% | **18.63%** | 92.9% | **WITHHOLD** |
| `photo_editor:paid_subscription` | 29.23% | 31.32% | 85.7% | **WITHHOLD** |
| `photo_editor:revenue_gbp` | 28.75% | 31.04% | 89.3% | **WITHHOLD** |

The most useful counterexample is `photo_editor:dau`:

```text
weekly seasonal-naive WAPE = 3.92%
last-value benchmark WAPE   = 2.56%
absolute-accuracy gate      = PASS
benchmark gate              = FAIL
final decision              = WITHHOLD
```

The candidate error looks good in isolation, but the extra model structure does not earn its place against a simpler benchmark. v0.34 therefore reduces the reference from three approved DAU forecasts to two approved metrics overall. That is a stricter evidence standard, not a deterioration in the underlying series.

### Leakage-safe interval calibration

For each forecast origin, the interval radius is calibrated only from absolute lag-7 residuals observable at that origin. The finite-sample order statistic is explicit:

```text
k = ceil((n + 1) × (1 - alpha)), capped at n
```

The implementation rejects horizons longer than the seasonal lag, because otherwise a lag-7 source for later targets could itself fall inside the future holdout window.

The interval coverage reported above is an empirical rolling-origin diagnostic. It is not a claim that the synthetic forecast intervals have production-calibrated future coverage.

### Plan-vs-actual reconciliation

For every historical origin the workbench stores the seven daily forecast rows and then reconciles them against the subsequently observed seven-day totals. Only metrics that pass the forecast decision contract are planning-eligible; withheld metrics retain diagnostic backtest evidence but cannot silently become authorised planning inputs.

Generated v0.34 forecast evidence:

```text
forecast_contract.json
forecast_backtest.csv
forecast_evaluations.csv
forecast_reconciliation.csv
```

`validate_forecast_plan.py` independently rebuilds all **252 row-level forecast points** from `gold_daily_metrics.csv` and `silver_events.csv`, checks origin boundaries, lag sources, candidate and benchmark errors, interval calibration, gate decisions and reconciliation semantics rather than trusting generated forecast summaries.

See [`docs/FORECAST_DECISIONING.md`](docs/FORECAST_DECISIONING.md).

## v0.33: counterfactual impact is not authorised impact

The pricing experiment reference remains unchanged:

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

The guardrail evidence planner uses the same `ddof=1` difference-in-proportions confidence-interval convention as the experiment. Conditional on the observed arm rates remaining representative:

```text
current arm size          = 4,000
conditional target        = 6,393 / arm
conditional increment     = 2,393 / arm
```

The integer boundary is audited directly: 6,393 passes the projected rule and 6,392 does not. This is conditional evidence planning, not a power guarantee.

The downstream synthetic launch scenario contains three 100,000-user eligible cohorts with hypothetical adoption shares of 25%, 50% and 75%, giving 150,000 counterfactual treated users. Each cohort contributes only its own first 30-day outcome:

```text
counterfactual incremental revenue  = £102,762.12
95% interval                        = [£82,714.46, £122,809.79]

experiment action                   = HOLD
planning status                     = counterfactual_only
decision-authorised rollout         = false
authorised treated users            = 0
authorised incremental revenue      = null
```

A positive economic scenario therefore remains visibly separate from an authorised product decision.

See [`docs/IMPACT_PLANNING.md`](docs/IMPACT_PLANNING.md) and [`docs/EXPERIMENT_DECISIONING.md`](docs/EXPERIMENT_DECISIONING.md).

## Freshness evidence ladder

Freshness decisions remain separated into four evidence levels:

```text
48h   = shortest feasible candidate at the final 2026-04-30 snapshot
96h   = shortest candidate observed feasible in all 9 rolling windows
none  = candidate certified at 95% family-wise confidence
96h   = only candidate whose current certification gap is evidence-depth-only
```

These statements are not interchangeable. A policy can look feasible at one snapshot, remain feasible across observed windows, and still lack enough information for a simultaneous confidence claim.

### Hard watermark risk budget

The same four constraints are carried through calibration, rolling backtesting, uncertainty analysis and evidence planning:

```text
late-event fraction among finalizable events <= 0.50%
revised finalized KPI-cell fraction          <= 1.00%
max |single revenue revision|                 <= £10
max |paid-subscription revision|              <= 1
```

There is no weighted score and no post-hoc relaxation.

### Observed stability is not statistical certification

Nine weekly processing snapshots from 2026-03-05 through 2026-04-30 produce the shortest-feasible sequence:

```text
72h, 72h, 72h, 96h, 48h, 48h, 48h, 48h, 48h
```

| Candidate | Feasible windows | Family-wise certified windows |
|---|---:|---:|
| 24h | 0 / 9 | 0 / 9 |
| 48h | 5 / 9 | 0 / 9 |
| 72h | 8 / 9 | 0 / 9 |
| 96h | **9 / 9** | **0 / 9** |

The uncertainty layer applies 95% family-wise Bonferroni control over 72 simultaneous one-sided exact Clopper–Pearson bounds. Current evidence therefore supports an observed-stability statement for 96h, but **no candidate is statistically certified** under the declared model.

### Prospective certification evidence

For the 96h candidate, the current certification gap is evidence-depth-only under the stated rates and hard gates:

```text
required finalizable-event trials   = 2,733,153
required finalized KPI cells        = 2,011
late-event audited cycle             = 206
revised-cell audited cycle           = 333
combined planning depth              = 1,330 days (~3.64 years)
global_monotonic_threshold_claimed   = false
```

The 1,330-day figure is a conditional evidence-depth calculation, not a promise that waiting that many additional wall-clock days will certify the policy.

See [`docs/LATE_ARRIVAL_GOVERNANCE.md`](docs/LATE_ARRIVAL_GOVERNANCE.md), [`docs/WATERMARK_CALIBRATION.md`](docs/WATERMARK_CALIBRATION.md), [`docs/WATERMARK_STABILITY.md`](docs/WATERMARK_STABILITY.md), [`docs/WATERMARK_UNCERTAINTY.md`](docs/WATERMARK_UNCERTAINTY.md) and [`docs/CERTIFICATION_EVIDENCE_PLANNING.md`](docs/CERTIFICATION_EVIDENCE_PLANNING.md).

## Point-in-time metric governance

Earlier evidence contracts remain active:

- **Retention maturity:** only cohorts whose D7/D30 target date is observable by `analysis_as_of` enter the denominator; immature cohorts remain explicit exclusions rather than churn.
- **DAU semantics:** current DAU uses explicit `app_open`; the deprecated any-event definition overstates mean DAU by 2.21%–5.27% in the reference data.
- **Forecast maturity:** every product forecast is evaluated only through the last observable `first_open` boundary and every rolling origin uses data available on or before that origin.
- **Processing time:** `event_ts` and `ingested_at` are separate; late events are preserved, reconciled and backfilled idempotently rather than silently discarded after nominal finalisation.

## Validation layers

```text
pytest
  -> 75 implementation and regression tests, including Python/DuckDB SQL parity

validate_build.py
  -> generic reference-build invariants

validate_forecast_plan.py
  -> independent rolling-origin forecast, benchmark, interval and reconciliation recomputation

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

The forecast, experiment and impact validators recompute from lower-level evidence rather than trusting generated summary artifacts. A method or data change that moves a published boundary must fail a claim gate until the public evidence is reviewed and updated.

The final v0.34 CI reference contains **47 SHA-256-manifested portable artifacts**; the uploaded GitHub Actions evidence bundle also contains `MANIFEST.json` and the DuckDB database.

## Quick start

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -e .
make check
```

`make check` runs the unit tests, builds the full deterministic reference, and then executes every independent validator above.

## Reproducibility boundary

Current numerical claims must either be regenerated by the present workflow and checked in CI or explicitly labelled as preserved historical context. The acquisition process, ingestion delays, forecast series, candidate watermark grid, risk budgets, pricing experiment and launch-cohort scale are synthetic/reference assumptions, not estimates of any real company's infrastructure or customers.

The forecast intervals are rolling-origin empirical planning evidence, not a production coverage guarantee; the workbench does not sum marginal daily forecast intervals into a false aggregate 90% interval.

The watermark binomial uncertainty layer treats event/cell indicators as Bernoulli observations; batch-, source- and day-level dependence is not yet included. Prospective watermark sample-size calculations condition on observed planning rates remaining representative.

The pricing experiment is fixed-horizon. Sequential monitoring, repeated peeking, network interference and cross-experiment interaction are outside the current claim. Impact planning does not assume effect persistence beyond 30 days and does not model acquisition-mix shifts, saturation, refunds, platform fees or contribution margin.

See [`docs/FORECAST_DECISIONING.md`](docs/FORECAST_DECISIONING.md), [`docs/IMPACT_PLANNING.md`](docs/IMPACT_PLANNING.md), [`docs/EXPERIMENT_DECISIONING.md`](docs/EXPERIMENT_DECISIONING.md), [`docs/LATE_ARRIVAL_GOVERNANCE.md`](docs/LATE_ARRIVAL_GOVERNANCE.md), [`docs/WATERMARK_CALIBRATION.md`](docs/WATERMARK_CALIBRATION.md), [`docs/WATERMARK_STABILITY.md`](docs/WATERMARK_STABILITY.md), [`docs/WATERMARK_UNCERTAINTY.md`](docs/WATERMARK_UNCERTAINTY.md), [`docs/CERTIFICATION_EVIDENCE_PLANNING.md`](docs/CERTIFICATION_EVIDENCE_PLANNING.md) and [`docs/REPRODUCIBILITY.md`](docs/REPRODUCIBILITY.md).
