# Product Analytics & Data Reliability Workbench

**Version:** v0.26  
**Stack:** Python · DuckDB · SQL · Pandas · NumPy · SciPy · Statsmodels · Pytest · GitHub Actions

A reproducible analytics workbench for a synthetic portfolio of subscription products. It is organised around one practical question:

> When a product KPI moves, can the team trust the number, explain the movement, and make a defensible decision using only evidence actually available at the reporting time?

The repository combines event certification, metric contracts, revenue reconciliation, point-in-time retention, forecast gates, experiment guardrails, processing-time freshness and evidence provenance in one auditable workflow.

All data and results are synthetic, controlled-fault outputs or explicitly labelled planning stress tests. Nothing here is presented as production-company performance.

## Verified v0.26 reference run

The 120-day deterministic reference uses `seed=2206`. GitHub Actions has reproduced the full pipeline and independent build validator on the v0.26 implementation.

| Check | Verified result |
|---|---:|
| Raw events | **276,249** |
| Rejected / certified rows | **589 / 275,660** |
| Raw revenue overstatement | **9.13%–10.96%** |
| Paid / first-open | **16.17%** |
| Paid / trial-start | **48.55%** |
| DAU forecasts approved | **3 / 3** |
| DAU MAPE | **3.9%–5.9%** |
| Revenue / subscription forecasts withheld | **6 / 6** |
| Revenue / subscription MAPE | **25.6%–37.3%** |
| Unit + Python/SQL parity tests | **36 passed** |
| Portable artifacts in SHA-256 manifest | **23** |

Commercial, DAU and mature-retention truth remains numerically stable from v0.25. v0.26 adds an independent processing-time stream rather than redrawing user behaviour.

## v0.26: event time is not processing time

A trustworthy metric system needs to distinguish when an event happened from when the analytics platform received it.

```text
event_ts     = business/event time
ingested_at  = processing time
```

The generator uses a third deterministic RNG stream for ingestion delay, separate from both commercial outcomes and activity. Therefore adding lateness does not silently change acquisition, trial, purchase or app-open truth.

The event contract is versioned to **1.2**. Generated v0.26 events include `ingested_at`; legacy inputs without that column remain supported and are interpreted as immediate arrivals (`ingested_at = event_ts`). New-schema certification rejects an explicitly supplied processing timestamp that is invalid or earlier than the event timestamp.

## 48-hour watermark reference policy

The current reference policy is intentionally simple and auditable:

```text
allowed lateness = 48 hours
processing snapshot = 2026-04-30 23:59:59.999999 UTC
watermark event date = 2026-04-28

final       if event_date <= 2026-04-28
provisional otherwise
```

The 48-hour value is a **reference operating policy, not a claim of optimality**. A later version can compare candidate watermarks against explicit revision-risk constraints.

### Verified processing-time evidence

Among 275,660 certified events, **1,367** arrive more than 48 hours after `event_ts`: **0.496%** of certified rows.

At the 2026-04-30 processing snapshot, the 48-hour watermark would already have called event dates through 2026-04-28 final. Nevertheless, **24 events** for those nominally-final dates had still not arrived. Settling the data later changes **8 product-date-metric cells**.

| Product | Metric | Finalized cells revised | Total revision | Largest single revision |
|---|---|---:|---:|---:|
| File Transfer | DAU | 2 | +2 users | +1 user |
| Notes App | DAU | 2 | +8 users | +4 users |
| Notes App | Revenue | 1 | +£7.99 | +£7.99 |
| Photo Editor | DAU | 2 | +7 users | +4 users |
| Photo Editor | Paid subscriptions | 1 | +1 | +1 |

The other product/metric combinations have zero finalized-cell revision in this snapshot.

This is deliberately a small incident, not a manufactured catastrophe. Most late events do not necessarily change a KPI because metric semantics such as distinct-user DAU and event type determine whether a row contributes to the aggregate.

## Late-arrival operating path

```text
event_ts
   |
   v
ingested_at
   |
   v
processing delay
   |
   v
48h watermark
   |-----------------------|
   v                       v
provisional dates     nominally final dates
                           |
                           v
                  late-arrival exception
                           |
                           v
                     reconciliation
                           |
                           v
                idempotent keyed backfill
                           |
                           v
                 KPI revision evidence
```

Late events are never silently discarded because a date was previously called final. The build writes both row-level exceptions and metric-level revisions:

```text
late_arrival_contract.json
late_arrival_summary.csv
watermark_late_events.csv
watermark_metric_revisions.csv
watermark_revision_summary.csv
```

`watermark_late_events.csv` answers *which events arrived after a nominal finalization decision?* `watermark_metric_revisions.csv` separately answers *which KPI cells actually changed?*

## v0.25: retention maturity remains point-in-time

The previous release fixed a different form of look-ahead. A source table may already contain follow-up events after the date of a report; those future outcomes must not enter a recent cohort's retention denominator.

The reference declares:

```text
analysis_as_of = final first_open date in reporting window
               = 2026-04-30

target_date = cohort_date + horizon
mature      = target_date <= analysis_as_of
```

Only mature cohorts enter D7/D30 retention. Immature cohorts remain visible in a maturity ledger with `eligible_users=0`, explicit excluded-user counts and null retention outcomes.

| Product | Horizon | Eligible users | Excluded users | Eligible fraction | Retention among eligible |
|---|---:|---:|---:|---:|---:|
| File Transfer | D7 | 9,450 | 573 | **94.28%** | **19.56%** |
| File Transfer | D30 | 7,426 | 2,597 | **74.09%** | **6.36%** |
| Notes App | D7 | 8,643 | 525 | **94.27%** | **38.35%** |
| Notes App | D30 | 6,947 | 2,221 | **75.77%** | **21.88%** |
| Photo Editor | D7 | 10,352 | 637 | **94.20%** | **26.82%** |
| Photo Editor | D30 | 8,199 | 2,790 | **74.61%** | **11.20%** |

Every product has 120 acquisition cohorts. D7 has 113 mature / 7 immature cohorts; D30 has 90 mature / 30 immature cohorts.

**Important:** lower D30 eligibility is evidence maturity, not worse retention.

## Explicit activity and DAU migration

DAU uses the v2 metric contract:

```text
DAU v1 (deprecated) = unique users with any certified event
DAU v2              = unique users with app_open
```

Both definitions run on the same certified stream. The verified legacy overstatement is **5.27%** for File Transfer, **2.21%** for Notes App and **4.35%** for Photo Editor.

## Data reliability flow

```text
Synthetic events
      |
      | event_ts + ingested_at
      v
Bronze raw events
      |
      +----> rejected_events + reject_reason
      |
      v
Silver certified events
      |
      +----> processing-latency / watermark evidence
      +----> revenue reconciliation
      |
      v
Gold daily metrics
      |
      +----> DAU v1/v2 migration
      +----> forecast evaluation
      +----> retention maturity ledger
      |          |---- mature ----> D7/D30 retention
      |          `---- immature --> explicit exclusion
      |
      +----> event / metric / retention / freshness contracts
      `----> SHA-256 manifest
```

Certification rejects duplicate IDs, missing identities, invalid event or ingestion timestamps, processing-before-event chronology, invalid revenue, unknown products/events and non-zero revenue on non-purchase events. Rejected rows remain inspectable with their `reject_reason`.

## Python / DuckDB SQL parity

The `sql/` directory is tested code rather than illustrative syntax. CI independently executes and compares SQL with Python for:

- Silver certification;
- Gold daily metrics;
- retention maturity ledger;
- processing-latency / late-arrival summaries.

The retention comparison covers target date, `analysis_as_of`, maturity status, eligible/excluded users, retained users, rate and exclusion reason. The freshness comparison verifies processing delay and late-watermark counts by product and event type.

## Forecast governance

For each product, the workflow evaluates DAU, revenue and paid subscriptions with a seven-day seasonal-naive baseline over a 28-point holdout. The final-`first_open` event-time boundary prevents simulator follow-up from leaking into the forecast history.

In the verified run:

- all three DAU baselines pass at **3.9%–5.9% MAPE**;
- all six revenue/subscription baselines are withheld at **25.6%–37.3% MAPE** under the unchanged 20% gate.

```text
model executed successfully != forecast approved for planning
```

## Metric and decision contracts

Metric definitions store numerator, denominator, grain, unit and version. Retention contracts additionally store cohort event, return event, horizon and exact-calendar-day return window. The late-arrival contract stores event-time field, processing-time field, allowed lateness, processing snapshot, watermark boundary and backfill action.

Pricing decisions keep commercial evidence and customer-safety evidence separate. Revenue upside cannot mathematically compensate for a harmful customer state.

See [`docs/METRIC_CONTRACTS.md`](docs/METRIC_CONTRACTS.md) and [`docs/LATE_ARRIVAL_GOVERNANCE.md`](docs/LATE_ARRIVAL_GOVERNANCE.md).

## Repository structure

```text
.
├── src/product_analytics/
│   ├── config.py
│   ├── generator.py
│   ├── contracts.py
│   ├── quality.py
│   ├── metrics.py
│   ├── freshness.py
│   ├── forecasting.py
│   ├── experiments.py
│   ├── risk_design.py
│   ├── provenance.py
│   └── pipeline.py
├── sql/
│   ├── silver_events.sql
│   ├── gold_daily_metrics.sql
│   ├── activity_retention_maturity.sql
│   └── late_arrival_summary.sql
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

The current build adds five processing-time/watermark artifacts to the existing certified pipeline outputs. In total **23 portable CSV/JSON artifacts** are hashed by `MANIFEST.json`. The GitHub Actions workflow artifact also includes `workbench.duckdb`.

## Reproducibility boundary

Current numerical claims must either be regenerated by the present workflow and checked in CI or explicitly labelled as preserved historical context. `results/risk_aware_design.csv` remains a preserved pre-v0.23 planning snapshot; it is not presented as a current regression target or production recommendation.

See [`docs/REPRODUCIBILITY.md`](docs/REPRODUCIBILITY.md).
