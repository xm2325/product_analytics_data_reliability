# Product Analytics & Data Reliability Workbench

**Version:** v0.35  
**Stack:** Python · DuckDB · SQL · Pandas · NumPy · SciPy · Statsmodels · Pytest · GitHub Actions

A reproducible analytics workbench for a synthetic portfolio of subscription products. It is organised around one practical question:

> When a product KPI moves, can the team trust the data and the metric definition, forecast it without future leakage, test a product change, and make a defensible business decision using only evidence that was actually available at the time?

The repository connects six evidence layers that are often demonstrated separately:

```text
data correctness
    ↓
contract evolution + metric semantic safety
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

The deterministic reference uses `seed=2206` and a 120-day acquisition window. The contract-migration replay spans the resulting 150 Gold calendar days across three products.

| Check | Reference result |
|---|---:|
| Raw events | **276,249** |
| Rejected / certified rows | **589 / 275,660** |
| Governed migration proposals | **3** |
| Migration actions | **1 APPROVE / 2 WITHHOLD** |
| Migration shadow replay | **450 product-day rows** |
| Max governed aggregate DAU shift | **+4.94%** |
| Forecast eligibility changes under semantic replay | **0 / 3** |
| Forecast metrics approved / withheld | **2 / 7** |
| Rolling forecast origins | **4 × 7-day horizons** |
| Forecast backtest points / metric | **28** |
| Pricing experiment users | **8,000** |
| Pricing experiment action | **HOLD** |
| Conditional paid-guardrail target | **6,393 users / arm** |
| Counterfactual treated users in launch scenario | **150,000** |
| Counterfactual 30d cohort revenue impact | **£102,762** |
| Decision-authorised treated users | **0** |
| Apr-30 point-in-time SLA | **48h** |
| Observed rolling-stable SLA | **96h** |
| Family-wise certified SLA | **none** |
| v0.35 unit tests | **81 passed** |
| Portable artifacts in reference manifest | **53** |

Three counterexamples summarise the design philosophy:

1. **Pipeline green does not mean metric-safe.** Broadening DAU from explicit `app_open` activity to any certified event leaves producers compatible and forecast eligibility unchanged, but moves governed DAU by up to **4.94%**, so the migration is **WITHHOLD**.
2. **Low forecast error does not mean planning-eligible.** `photo_editor:dau` has only **3.92% WAPE**, but a trivial last-value benchmark is better at **2.56%**, so the candidate is **WITHHOLD**.
3. **Positive revenue does not mean rollout.** The pricing experiment estimates **+£0.685/user/30d** with a positive 95% CI, but the paid-conversion guardrail remains unresolved, so the experiment is **HOLD** and the £102.8k launch impact remains counterfactual-only.

No weighted score allows one strong dimension to compensate for a failed hard gate.

## v0.35: technically green is not semantically safe

A schema migration can keep jobs green while silently changing what a KPI means. v0.35 therefore separates three questions:

```text
Can existing producers still satisfy the contract?
Does the governed metric remain within the declared semantic tolerance?
Does the downstream decision state remain unchanged?
```

The migration rule is non-compensatory:

```text
existing producers remain compatible
AND governed metric movement <= 1%
AND forecast eligibility is unchanged
→ APPROVE
otherwise → WITHHOLD
```

### Reference migration cases

| Proposal | Class | Producer compatible | Metric invariant | Forecast eligibility stable | Action |
|---|---|---:|---:|---:|---|
| add optional `country` | ADDITIVE | PASS | PASS | PASS | **APPROVE** |
| broaden DAU to any certified event | SEMANTIC | PASS | **FAIL** | PASS | **WITHHOLD** |
| rename required `event_id` → `event_uuid` | BREAKING | **FAIL** | PASS | PASS | **WITHHOLD** |

The semantic case is intentionally useful because downstream code continues to run and forecast decisions do not flip. The migration is still unsafe because the KPI meaning itself moved beyond the declared 1% tolerance.

### Shadow-replay evidence

The semantic proposal replays both DAU definitions over the same certified evidence while keeping paid-subscription and revenue as invariant controls.

| Product | Aggregate DAU shift | Max daily absolute DAU shift | Paid delta | Revenue delta |
|---|---:|---:|---:|---:|
| `file_transfer` | **+4.94%** | 11.96% | 0 | £0 |
| `notes_app` | **+2.04%** | 8.66% | 0 | £0 |
| `photo_editor` | **+4.04%** | 10.76% | 0 | £0 |

The downstream leakage-safe DAU forecasts are then recomputed under the candidate semantics:

| Product | Current WAPE | Candidate WAPE | Current decision | Candidate decision |
|---|---:|---:|---|---|
| `file_transfer` | 5.91% | 5.53% | APPROVE | APPROVE |
| `notes_app` | 3.97% | 4.06% | APPROVE | APPROVE |
| `photo_editor` | 3.92% | 3.77% | WITHHOLD | WITHHOLD |

So **0/3 forecast eligibility states change**. That does not rescue the semantic migration: a stable downstream decision cannot compensate for an upstream KPI-definition breach.

Generated v0.35 evidence:

```text
contract_registry.json
migration_proposals.json
migration_replay.csv
metric_change_impact.csv
migration_forecast_impact.csv
migration_decisions.json
```

`validate_contract_migration.py` independently reloads Gold/Silver evidence, reconstructs all **450 replay rows**, recomputes all **3 current-vs-candidate forecast comparisons**, reclassifies the proposals and rebuilds the migration actions instead of trusting stored decisions.

See [`docs/CONTRACT_EVOLUTION_GOVERNANCE.md`](docs/CONTRACT_EVOLUTION_GOVERNANCE.md).

## v0.34: forecast accuracy is not enough

The forecast layer keeps a transparent weekly seasonal-naive candidate but evaluates it as a decision input rather than a model-demo score.

```text
candidate model            = weekly seasonal naive, lag 7
benchmark                  = last observed value carried across each 7-day horizon
rolling origins            = 4
horizon                    = 7 days
backtest points            = 28 per metric
absolute metrics           = MAPE + WAPE
interval                   = 90% symmetric absolute seasonal-residual interval
interval calibration       = origin-specific; only pre-origin residuals
minimum empirical coverage = 85%
weighted score             = none
future-data leakage        = forbidden
```

Every gate must pass:

```text
enough backtest evidence
AND MAPE/WAPE <= 20%
AND candidate WAPE <= last-value benchmark WAPE
AND interval coverage >= 85%
→ forecast eligible for planning
```

### Reference forecast decisions

| Metric | Candidate WAPE | Last-value WAPE | 90% interval coverage | Decision |
|---|---:|---:|---:|---|
| `file_transfer:dau` | **5.91%** | 7.05% | 100.0% | **APPROVE** |
| `notes_app:dau` | **3.97%** | 4.64% | 100.0% | **APPROVE** |
| `photo_editor:dau` | 3.92% | **2.56%** | 100.0% | **WITHHOLD** |
| `file_transfer:paid_subscription` | 32.22% | 43.77% | 89.3% | WITHHOLD |
| `file_transfer:revenue_gbp` | 32.22% | 43.77% | 89.3% | WITHHOLD |
| `notes_app:paid_subscription` | 22.13% | **17.49%** | 92.9% | WITHHOLD |
| `notes_app:revenue_gbp` | 22.74% | **18.63%** | 92.9% | WITHHOLD |
| `photo_editor:paid_subscription` | 29.23% | 31.32% | 85.7% | WITHHOLD |
| `photo_editor:revenue_gbp` | 28.75% | 31.04% | 89.3% | WITHHOLD |

`photo_editor:dau` is the strongest counterexample: the model's absolute error looks good, but it does not earn its place against the simpler benchmark.

For each rolling origin, the interval radius is calibrated only from lag-7 residuals observable before that origin using the finite-sample order statistic:

```text
k = ceil((n + 1) × (1 - alpha)), capped at n
```

The implementation also rejects forecast horizons longer than the seasonal lag, preventing a later target's lag source from entering the future holdout window.

`validate_forecast_plan.py` independently reconstructs all **252 row-level rolling-origin forecast points** from lower-level evidence, including source dates, candidate and benchmark errors, interval calibration, gate decisions and plan-vs-actual reconciliation.

See [`docs/FORECAST_DECISIONING.md`](docs/FORECAST_DECISIONING.md).

## Experiment and impact: positive economics do not override guardrails

The deterministic pricing experiment remains deliberately **HOLD**:

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

Conditional on the observed arm rates remaining representative, the first equal-allocation arm size whose projected lower confidence bound clears the paid guardrail is **6,393 users per arm**, versus the current 4,000. The 6,393/6,392 integer boundary is audited directly; this is conditional evidence planning, not a power guarantee.

The synthetic launch scenario has three 100,000-user eligible cohorts at hypothetical 25%, 50% and 75% adoption, yielding 150,000 counterfactual treated users:

```text
counterfactual incremental revenue  = £102,762.12
95% interval                        = [£82,714.46, £122,809.79]
experiment action                   = HOLD
planning status                     = counterfactual_only
decision-authorised rollout         = false
authorised treated users            = 0
authorised incremental revenue      = null
```

See [`docs/EXPERIMENT_DECISIONING.md`](docs/EXPERIMENT_DECISIONING.md) and [`docs/IMPACT_PLANNING.md`](docs/IMPACT_PLANNING.md).

## Freshness evidence ladder

Processing-time policy is kept separate at four evidence levels:

```text
48h   = shortest feasible candidate at the final 2026-04-30 snapshot
96h   = shortest candidate observed feasible in all 9 rolling windows
none  = candidate certified at 95% family-wise confidence
96h   = only candidate whose current certification gap is evidence-depth-only
```

The same hard budget is retained throughout calibration, backtesting, uncertainty and evidence planning:

```text
late-event fraction among finalizable events <= 0.50%
revised finalized KPI-cell fraction          <= 1.00%
max |single revenue revision|                 <= £10
max |paid-subscription revision|              <= 1
```

Nine weekly processing snapshots produce the shortest-feasible sequence:

```text
72h, 72h, 72h, 96h, 48h, 48h, 48h, 48h, 48h
```

| Candidate | Feasible windows | Family-wise certified windows |
|---|---:|---:|
| 24h | 0 / 9 | 0 / 9 |
| 48h | 5 / 9 | 0 / 9 |
| 72h | 8 / 9 | 0 / 9 |
| 96h | **9 / 9** | **0 / 9** |

The uncertainty layer applies 95% family-wise Bonferroni control over **72 simultaneous one-sided exact Clopper–Pearson bounds**. Observed stability therefore does not get relabelled as statistical certification.

For the 96h candidate, the current certification gap is evidence-depth-only under the declared planning rates and hard gates:

```text
required finalizable-event trials   = 2,733,153
required finalized KPI cells        = 2,011
late-event audited cycle             = 206
revised-cell audited cycle           = 333
combined planning depth              = 1,330 days (~3.64 years)
global_monotonic_threshold_claimed   = false
```

See [`docs/LATE_ARRIVAL_GOVERNANCE.md`](docs/LATE_ARRIVAL_GOVERNANCE.md), [`docs/WATERMARK_CALIBRATION.md`](docs/WATERMARK_CALIBRATION.md), [`docs/WATERMARK_STABILITY.md`](docs/WATERMARK_STABILITY.md), [`docs/WATERMARK_UNCERTAINTY.md`](docs/WATERMARK_UNCERTAINTY.md) and [`docs/CERTIFICATION_EVIDENCE_PLANNING.md`](docs/CERTIFICATION_EVIDENCE_PLANNING.md).

## Point-in-time metric governance

Earlier evidence contracts remain active:

- **Retention maturity:** only cohorts whose D7/D30 target date is observable by `analysis_as_of` enter the denominator; immature cohorts remain explicit exclusions rather than churn.
- **DAU semantics:** the current production-style contract uses unique users with explicit `app_open`; the broader any-event definition is retained only as migration evidence.
- **Forecast maturity:** every rolling origin uses only evidence observable on or before that origin.
- **Processing time:** `event_ts` and `ingested_at` remain separate; late events are preserved, reconciled and backfilled idempotently rather than silently discarded after nominal finalisation.

## Independent validation chain

```text
pytest
  -> 81 implementation and regression tests, including Python/DuckDB SQL parity

build_reference.py
  -> deterministic full reference build

validate_build.py
  -> generic reference-build invariants

validate_forecast_plan.py
  -> independent 252-point rolling-origin forecast reconstruction

validate_contract_migration.py
  -> independent 450-row migration replay + 3 forecast comparisons + actions

validate_watermark_backtest.py
  -> point-in-time and rolling watermark accounting

validate_uncertainty_certification.py
  -> simultaneous-bound accounting and certification rules

validate_evidence_plan.py
  -> cycle-stable evidence-depth vs hard-gate classification

validate_pricing_experiment.py
  -> independent SRM, effect, uncertainty and experiment-decision recomputation

validate_impact_plan.py
  -> independent guardrail target, cohort impact and authorisation recomputation

validate_reference_claims.py
  -> pinned seed=2206 headline numerical claims

validate_static_claim_ledger.py
  -> checked-in public claim ledger must agree with generated evidence
```

A method, contract or data change that moves a published boundary must fail a claim gate until the public evidence is explicitly reviewed and updated.

The v0.35 reference contains **53 SHA-256-manifested portable artifacts**. GitHub Actions also uploads the complete validated evidence bundle, including `MANIFEST.json` and the DuckDB database.

## Quick start

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -e .
make check
```

`make check` runs all 81 tests, rebuilds the full deterministic reference, and executes every independent validator listed above.

## Reproducibility and claim boundaries

Current numerical claims must either be regenerated by the present workflow and checked in CI or explicitly labelled as preserved historical context. Acquisition, ingestion delays, migration proposals, forecast series, candidate watermark grid, risk budgets, experiment outcomes and launch-cohort scale are synthetic/reference assumptions.

The **1% migration semantic tolerance** is a declared reference governance threshold, not a universal production threshold. Real migrations would additionally require ownership, observability, staged rollout and rollback controls appropriate to the affected system.

Forecast intervals are rolling-origin empirical planning evidence, not a production coverage guarantee. The workbench does not sum marginal daily intervals into a false aggregate 90% interval.

The watermark binomial layer treats event/cell indicators as Bernoulli observations; batch-, source- and day-level dependence is not modelled. Prospective sample-size calculations condition on the observed planning rates and throughput remaining representative.

The pricing experiment is fixed-horizon. Sequential monitoring, repeated peeking, network interference and cross-experiment interaction are outside the current claim. Impact planning does not assume effect persistence beyond 30 days and does not model acquisition-mix shifts, saturation, refunds, platform fees or contribution margin.

See [`CHANGELOG.md`](CHANGELOG.md) for the evidence-driven release history and [`docs/REPRODUCIBILITY.md`](docs/REPRODUCIBILITY.md) for the broader reproducibility boundary.
