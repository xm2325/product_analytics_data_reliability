# Product Analytics & Data Reliability Workbench

**Version:** v0.25  
**Stack:** Python · DuckDB · SQL · Pandas · NumPy · SciPy · Statsmodels · Pytest · GitHub Actions

A reproducible analytics workbench for a synthetic portfolio of subscription products. It is organised around one practical question:

> When a product KPI moves, can the team trust the number, explain the movement, and make a defensible decision using only evidence available at the reporting date?

The repository combines event certification, metric contracts, revenue reconciliation, activity/retention metrics, forecast gates, experiment guardrails and evidence provenance in one auditable workflow.

All data and results are synthetic, controlled-fault outputs or explicitly labelled planning stress tests. Nothing here is presented as production-company performance.

## Verified v0.25 reference run

GitHub Actions reproduced and independently validated the 120-day reference (`seed=2206`):

| Check | Verified result |
|---|---:|
| Raw events | **276,249** |
| Rejected / certified rows | **589 / 275,660** |
| Raw revenue overstatement | **9.13%–10.96%** |
| Paid / first-open | **16.17%** |
| Paid / trial-start | **48.55%** |
| DAU v2 forecasts approved | **3 / 3** |
| DAU v2 MAPE | **3.9%–5.9%** |
| Revenue / subscription forecasts withheld | **6 / 6** |
| Revenue / subscription MAPE | **25.6%–37.3%** |
| Unit/parity tests | **29 passed** |
| Portable artifacts in SHA-256 manifest | **18** |

Commercial and DAU results remain numerically stable from v0.24. The v0.25 change is stricter **point-in-time retention denominator governance**.

## v0.25: retention maturity is part of the metric

A common source table may already contain follow-up events occurring after the date of a report. Using those events to evaluate a recent cohort would leak future information.

v0.25 therefore declares a shared reporting boundary:

```text
analysis_as_of = final first_open date in the reporting window
               = 2026-04-30 in the reference run
```

For an acquisition cohort and horizon `h`:

```text
target_date = cohort_date + h
mature      = target_date <= analysis_as_of
```

Only mature cohorts enter the retention denominator. Immature cohorts are **not dropped**: they remain in an auditable ledger with their users explicitly counted as excluded and with retention outcomes left null.

### Verified maturity and retention

| Product | Horizon | Eligible users | Excluded users | Eligible fraction | Retention among eligible |
|---|---:|---:|---:|---:|---:|
| File Transfer | D7 | 9,450 | 573 | **94.28%** | **19.56%** |
| File Transfer | D30 | 7,426 | 2,597 | **74.09%** | **6.36%** |
| Notes App | D7 | 8,643 | 525 | **94.27%** | **38.35%** |
| Notes App | D30 | 6,947 | 2,221 | **75.77%** | **21.88%** |
| Photo Editor | D7 | 10,352 | 637 | **94.20%** | **26.82%** |
| Photo Editor | D30 | 8,199 | 2,790 | **74.61%** | **11.20%** |

Every product has 120 acquisition cohorts. D7 has 113 mature / 7 immature cohorts; D30 has 90 mature / 30 immature cohorts.

**Important:** a lower D30 eligible fraction is not worse retention. It means fewer cohorts have had enough calendar time to become observable.

The machine-readable contracts are written to `retention_contracts.json`, and the full denominator audit is written to:

```text
retention_maturity_ledger.csv
retention_maturity_summary.csv
```

## Explicit activity and DAU migration

The current activity metric remains the v0.24 contract:

```text
DAU v1 (deprecated) = unique users with any certified event
DAU v2              = unique users with app_open
```

Both definitions run on the same certified stream. The verified legacy overstatement is **5.27%** for File Transfer, **2.21%** for Notes App and **4.35%** for Photo Editor.

Activity randomness is isolated from the commercial RNG, so adding or changing `app_open` simulation does not silently redraw acquisition, trial, paid or purchase outcomes.

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
      +----> forecast evaluations
      |
      +----> retention maturity ledger
                  |
                  +---- mature ----> D7/D30 retention
                  |
                  +---- immature --> explicit exclusion
      |
      +----> event / metric / retention contracts
      +----> SHA-256 manifest
```

Certification rejects duplicate IDs, missing identities, invalid timestamps/revenue, unknown products/events and non-zero revenue on non-purchase events. A rejected row remains inspectable with its `reject_reason`; it is not silently removed from the audit trail.

The build validator enforces, among other invariants:

```text
rows_raw = rows_certified + rows_rejected
mature eligible + mature excluded = cohort users
immature eligible = 0
immature retained/rate = NULL
D30 eligible fraction < D7 eligible fraction
```

## Python / DuckDB SQL parity

The `sql/` directory is tested code rather than illustrative syntax. CI independently executes:

- Silver certification SQL;
- Gold daily-metric SQL;
- retention-maturity SQL.

The results are compared against Python on the same controlled-fault events. The retention comparison covers the full cohort ledger: target date, `analysis_as_of`, maturity status, eligible/excluded users, retained users, rate and exclusion reason.

## Forecast governance

For each product, the workflow evaluates DAU v2, revenue and paid subscriptions with a seven-day seasonal-naive baseline over a 28-point holdout.

The same final-`first_open` boundary prevents the simulator's post-acquisition outcome tail from contaminating the forecast holdout. In the verified run:

- all three DAU baselines pass at **3.9%–5.9% MAPE**;
- all six revenue/subscription baselines are withheld at **25.6%–37.3% MAPE** under the unchanged 20% gate.

```text
model executed successfully != forecast approved for planning
```

## Metric and experiment contracts

Metric definitions store numerator, denominator, grain, unit and version. Retention contracts additionally store cohort event, return event, horizon and exact-calendar-day return window.

Pricing decisions likewise keep commercial evidence and customer-safety evidence separate. A rollout requires both a positive lower revenue confidence bound and clearance of the paid-conversion harm guardrail; revenue upside cannot compensate mathematically for a harmful state.

See [`docs/METRIC_CONTRACTS.md`](docs/METRIC_CONTRACTS.md).

## Repository structure

```text
.
├── src/product_analytics/
│   ├── config.py
│   ├── generator.py
│   ├── contracts.py
│   ├── quality.py
│   ├── metrics.py            # DAU, retention contracts + maturity ledger
│   ├── forecasting.py
│   ├── experiments.py
│   ├── risk_design.py
│   ├── provenance.py
│   └── pipeline.py
├── sql/
│   ├── silver_events.sql
│   ├── gold_daily_metrics.sql
│   └── activity_retention_maturity.sql
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

The v0.25 build adds maturity evidence to the existing certified pipeline outputs:

```text
retention_contracts.json
retention_maturity_ledger.csv
retention_maturity_summary.csv
activity_retention_cohorts.csv
activity_retention_summary.csv
```

Together with the existing Bronze/Silver/Gold, reconciliation, DAU migration, forecast, quality and contract outputs, **18 portable CSV/JSON artifacts** are covered by `MANIFEST.json`; the workflow artifact also includes `workbench.duckdb`.

## Reproducibility boundary

Current numerical claims must either be regenerated by the present workflow and checked in CI or explicitly labelled as preserved historical context. `results/risk_aware_design.csv` remains such a preserved planning snapshot; it is not presented as a current regression target or production recommendation.

See [`docs/REPRODUCIBILITY.md`](docs/REPRODUCIBILITY.md).
