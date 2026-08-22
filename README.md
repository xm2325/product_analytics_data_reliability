# Product Analytics & Data Reliability Workbench

**Version:** v0.24  
**Stack:** Python · DuckDB · SQL · Pandas · NumPy · SciPy · Statsmodels · Pytest · GitHub Actions

A reproducible analytics workbench for a synthetic portfolio of subscription products. It is organised around one practical question:

> When a product KPI moves, can the team trust the number, explain the movement, and make a defensible decision?

The repository combines event certification, metric contracts, revenue reconciliation, activity/retention metrics, forecasting gates, experiment guardrails and risk-aware evidence planning in one auditable workflow.

All data and results are synthetic, controlled-fault outputs or explicitly labelled planning stress tests. Nothing here is presented as production-company performance.

## Verified v0.24 reference run

GitHub Actions reproduced and validated the 120-day reference run with `seed=2206`:

| Check | Verified result |
|---|---:|
| Raw events | **276,249** |
| Rejected rows | **589** |
| Certified rows | **275,660** |
| Raw revenue overstatement across products | **9.13%–10.96%** |
| Paid conversion from first-open | **16.17%** |
| Paid conversion conditional on trial-start | **48.55%** |
| DAU v2 forecasts approved | **3 / 3** |
| DAU v2 MAPE | **3.9%–5.9%** |
| Revenue / paid-subscription forecasts withheld | **6 / 6** |
| Revenue / paid-subscription MAPE | **25.6%–37.3%** |
| Portable artifacts covered by SHA-256 manifest | **15** |

Commercial funnel and revenue results are unchanged from v0.23 because v0.24 gives product activity its own deterministic RNG stream. Adding `app_open` therefore does not silently redraw acquisition, trial, paid or purchase outcomes.

## v0.24: define active use explicitly

The previous compact metric counted a user as daily active when they generated **any** certified event. That is convenient but semantically weak: a delayed purchase or subscription event does not necessarily mean the user opened or used the product that day.

v0.24 introduces explicit `app_open` activity and a versioned migration:

```text
DAU v1 (deprecated) = unique users with any certified event
DAU v2              = unique users with app_open
```

Both definitions run on the same certified event stream before the old one is retired.

The verified mean migration effect is:

| Product | Mean DAU v2 | Mean legacy DAU | Legacy overstatement |
|---|---:|---:|---:|
| File Transfer | 387.2 | 407.7 | **5.27%** |
| Notes App | 733.2 | 749.4 | **2.21%** |
| Photo Editor | 584.9 | 610.4 | **4.35%** |

This is why metric migration is treated as a data-product change rather than renaming a dashboard field.

## Activity retention

The synthetic activity process creates one binary daily-return opportunity per user, with product-specific decaying return probability. Day-0 activity is explicit, and D7/D30 retention is defined by an `app_open` exactly 7 or 30 calendar days after first-open.

Verified reference retention:

| Product | D7 | D30 |
|---|---:|---:|
| File Transfer | **19.6%** | **6.2%** |
| Notes App | **38.2%** | **21.9%** |
| Photo Editor | **26.7%** | **11.4%** |

These are simulator outputs, not real-product benchmarks.

## Data reliability flow

```text
Synthetic events
      |
      v
Bronze raw events
      |
      +----> rejected_events + reject_reason
      |
      v
Silver certified events
      |
      +----> revenue_reconciliation
      |
      v
Gold daily metrics
      |
      +----> DAU v1/v2 migration
      +----> D7/D30 activity retention
      +----> forecast evaluations
      +----> metric/event contracts
      +----> SHA-256 manifest
```

Certification rejects duplicate IDs, missing identities, invalid timestamps/revenue, unknown products/events and non-zero revenue on non-purchase events. A rejected row remains inspectable with a semicolon-separated `reject_reason`; it is not silently discarded from the audit trail.

The validator enforces:

```text
rows_raw = rows_certified + rows_rejected
```

## Metric contracts

The generated registry makes numerator, denominator, grain, unit and version explicit. Current activity contracts are:

```text
daily_active_users                    v2.0
daily_active_users_legacy_any_event   v1.0-deprecated
```

Conversion contracts remain separately defined as paid / first-open and paid / trial-start. Their verified values are 16.17% and 48.55%; the difference is a denominator choice, not a contradiction.

See [`docs/METRIC_CONTRACTS.md`](docs/METRIC_CONTRACTS.md).

## Forecast gate

The workflow evaluates DAU v2, revenue and paid subscriptions for each product with a seven-day seasonal-naive baseline over a 28-point holdout.

An explicit observation-maturity boundary trims dates after the final `first_open` before forecast validation. Delayed outcomes remain in historical metrics, but the simulator's artificial post-acquisition tail is not treated as a real product collapse.

In the verified v0.24 run:

- all three `app_open` DAU forecasts pass at **3.9%–5.9% MAPE**;
- all six revenue/subscription forecasts remain above the 20% planning gate at **25.6%–37.3% MAPE** and are withheld.

The revenue/subscription errors are numerically unchanged from v0.23, providing a regression check that the activity extension did not alter the commercial stream.

```text
model executed successfully != forecast approved for planning
```

## Experiment guardrails

Pricing decisions keep commercial evidence and customer-safety evidence separate. A rollout requires both:

```text
lower 95% CI for revenue effect > 0
AND
lower 95% CI for paid-conversion effect > declared harm guardrail
```

Revenue upside is not allowed to mathematically compensate for a harmful conversion state.

## Risk-aware allocation snapshot

`results/risk_aware_design.csv` preserves a planning snapshot from the earlier unequal-randomisation study. The compact package retains the allocation mathematics and constraint objects, but not the full historical Monte Carlo portfolio-risk engine.

It is therefore a **preserved planning snapshot**, not a current-workflow regression target or production recommendation. See [`docs/REPRODUCIBILITY.md`](docs/REPRODUCIBILITY.md).

## Repository structure

```text
.
├── src/product_analytics/
│   ├── config.py
│   ├── generator.py          # commercial + isolated activity RNG streams
│   ├── contracts.py
│   ├── quality.py
│   ├── metrics.py            # DAU v2, dual-run migration, retention
│   ├── forecasting.py
│   ├── experiments.py
│   ├── risk_design.py
│   ├── provenance.py
│   └── pipeline.py
├── sql/
├── scripts/
│   ├── run_workbench.py
│   └── validate_build.py
├── tests/
├── results/
├── docs/
└── .github/workflows/ci.yml
```

## Quick start

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -e .

python scripts/run_workbench.py --output-dir build/reference
python scripts/validate_build.py build/reference
pytest -q
```

Or run the full local gate:

```bash
make check
```

## Generated reference evidence

A successful v0.24 build contains the certified pipeline outputs plus:

```text
product_config.csv
dau_definition_migration.csv
dau_definition_migration_summary.csv
activity_retention_cohorts.csv
activity_retention_summary.csv
forecast_evaluations.csv
metric_contracts.json
event_contract.json
reference_summary.json
MANIFEST.json
workbench.duckdb
```

`MANIFEST.json` stores file size and SHA-256 for all 15 portable CSV/JSON artifacts. `scripts/validate_build.py` also checks semantic invariants including the DAU migration direction, retention bounds/decay, product coverage and contract versions.

## Reproducibility boundary

The repository intentionally separates current reproducible evidence from preserved historical planning snapshots. Numerical README claims must either be regenerated by the current workflow or explicitly labelled as preserved context.

See [`docs/REPRODUCIBILITY.md`](docs/REPRODUCIBILITY.md).
