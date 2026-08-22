# Product Analytics & Data Reliability Workbench

**Version:** v0.27  
**Stack:** Python · DuckDB · SQL · Pandas · NumPy · SciPy · Statsmodels · Pytest · GitHub Actions

A reproducible analytics workbench for a synthetic portfolio of subscription products. It is organised around one practical question:

> When a product KPI moves, can the team trust the number, explain the movement, and make a defensible decision using only evidence actually available at the reporting time?

The repository combines event certification, metric contracts, revenue reconciliation, point-in-time retention, forecast gates, experiment guardrails, processing-time freshness, watermark calibration and evidence provenance in one auditable workflow.

All data and results are synthetic, controlled-fault outputs or explicitly labelled planning stress tests. Nothing here is presented as production-company performance.

## Verified v0.27 reference run

The 120-day deterministic reference uses `seed=2206`. GitHub Actions has reproduced the pipeline, generic build validator and pinned-reference claim validator.

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
| Unit + Python/SQL parity/calibration tests | **38 passed** |
| Portable artifacts in SHA-256 manifest | **25** |

Commercial, DAU and mature-retention truth remains numerically stable from v0.25. v0.26 added processing time without redrawing behaviour; v0.27 reuses that same evidence to choose a reference finalization SLA.

## v0.27: why is the watermark 48 hours?

v0.26 deliberately treated 48 hours as a reference policy rather than claiming it was optimal. v0.27 makes the choice auditable.

Four candidate finalization lags are replayed against the **same certified event stream** and the **same 2026-04-30 processing snapshot**:

```text
24h · 48h · 72h · 96h
```

The reference risk budget is expressed as four hard constraints:

```text
late-event fraction                  <= 0.50%
revised finalized KPI-cell fraction  <= 1.00%
max |single revenue revision|         <= £10
max |paid-subscription revision|      <= 1
```

There is **no weighted score**. Revenue revision, event lateness and KPI revision rate stay in their natural units and cannot compensate for one another.

### Candidate replay

| Candidate | Finalization lag | Late-event fraction | Missing after nominal finalization | Revised KPI cells | Revised-cell fraction | Max revenue revision | Max paid revision | Feasible? |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| 24h | 1 day | **6.958%** | 62 | 13 / 1,071 | **1.214%** | £9.99 | 1 | **No** |
| 48h | 2 days | **0.496%** | 24 | 8 / 1,062 | **0.753%** | £7.99 | 1 | **Yes** |
| 72h | 3 days | **0.496%** | 11 | 4 / 1,053 | **0.380%** | £0.00 | 1 | **Yes** |
| 96h | 4 days | **0.482%** | 0 | 0 / 1,044 | **0.000%** | £0.00 | 0 | **Yes** |

The decision rule is therefore:

```text
minimize finalization lag
subject to every risk constraint passing
```

The 24-hour candidate fails both the late-event-fraction and revised-KPI-cell-fraction gates. **48 hours is the shortest feasible candidate.** The 72/96-hour policies reduce revision risk further, but cost one or two extra days of freshness, so they do not win simply because their risk is lower.

Generated decision evidence:

```text
watermark_policy_grid.csv
watermark_policy_decision.json
```

See [`docs/WATERMARK_CALIBRATION.md`](docs/WATERMARK_CALIBRATION.md).

## Reference-claim drift is a CI failure

The generic validator checks invariants such as candidate monotonicity, constraint accounting and “shortest feasible” selection. v0.27 adds a second deterministic-reference gate because published results can otherwise become stale while code continues to pass generic tests.

For the pinned `seed=2206`, `days=120` reference:

```text
24h must remain infeasible
24h must fail late-event and revised-cell fraction gates
48h must remain feasible
selected SLA must remain 48h
```

If later code, metric semantics or synthetic data moves that boundary, CI fails and forces the public claim to be reviewed.

## v0.26: event time is not processing time

A trustworthy metric system distinguishes when an event happened from when the analytics platform received it:

```text
event_ts     = business/event time
ingested_at  = processing time
```

The generator uses a dedicated ingestion RNG, separate from commercial and activity randomness. Adding lateness therefore does not silently change acquisition, trial, purchase or app-open truth.

Generated events include `ingested_at`; legacy inputs without that column remain supported and are interpreted as immediate arrivals (`ingested_at = event_ts`). Explicit processing timestamps that are invalid or earlier than event time are rejected.

Under the selected 48-hour reference policy, 1,367 of 275,660 certified rows arrive beyond the watermark (**0.496%**). At the processing snapshot, **24 events** for nominally-final dates had not yet arrived. Settling them changes **8 product-date-metric cells**:

| Product | Metric | Finalized cells revised | Total revision | Largest single revision |
|---|---|---:|---:|---:|
| File Transfer | DAU | 2 | +2 users | +1 user |
| Notes App | DAU | 2 | +8 users | +4 users |
| Notes App | Revenue | 1 | +£7.99 | +£7.99 |
| Photo Editor | DAU | 2 | +7 users | +4 users |
| Photo Editor | Paid subscriptions | 1 | +1 | +1 |

A late row is not automatically a KPI revision: distinct-user semantics and event type determine whether the aggregate changes.

### Late-arrival operating path

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
watermark
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

Late events are never silently discarded because a date was previously called final. The build preserves both row-level exceptions and metric-level revisions:

```text
late_arrival_contract.json
late_arrival_summary.csv
watermark_late_events.csv
watermark_metric_revisions.csv
watermark_revision_summary.csv
```

See [`docs/LATE_ARRIVAL_GOVERNANCE.md`](docs/LATE_ARRIVAL_GOVERNANCE.md).

## v0.25: retention maturity remains point-in-time

A source table may contain follow-up events after the date of a report. Those future outcomes must not enter a recent cohort's retention denominator.

The reference declares:

```text
analysis_as_of = final first_open date in reporting window
               = 2026-04-30

target_date = cohort_date + horizon
mature      = target_date <= analysis_as_of
```

Only mature cohorts enter D7/D30 retention. Immature cohorts remain visible with `eligible_users=0`, explicit exclusions and null outcomes.

| Product | Horizon | Eligible users | Excluded users | Eligible fraction | Retention among eligible |
|---|---:|---:|---:|---:|---:|
| File Transfer | D7 | 9,450 | 573 | **94.28%** | **19.56%** |
| File Transfer | D30 | 7,426 | 2,597 | **74.09%** | **6.36%** |
| Notes App | D7 | 8,643 | 525 | **94.27%** | **38.35%** |
| Notes App | D30 | 6,947 | 2,221 | **75.77%** | **21.88%** |
| Photo Editor | D7 | 10,352 | 637 | **94.20%** | **26.82%** |
| Photo Editor | D30 | 8,199 | 2,790 | **74.61%** | **11.20%** |

Every product has 120 acquisition cohorts. D7 has 113 mature / 7 immature cohorts; D30 has 90 mature / 30 immature cohorts.

**Lower D30 eligibility is evidence maturity, not worse retention.**

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
      +----> processing latency / watermark evidence
      +----> watermark policy calibration
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

Certification rejects duplicate IDs, missing identities, invalid event or ingestion timestamps, processing-before-event chronology, invalid revenue, unknown products/events and non-zero revenue on non-purchase events. Rejected rows remain inspectable with `reject_reason`.

## Python / DuckDB SQL parity

The `sql/` directory is tested code rather than illustrative syntax. CI independently executes and compares SQL with Python for Silver certification, Gold daily metrics, retention maturity and processing-latency summaries.

The retention comparison covers target date, `analysis_as_of`, maturity status, eligible/excluded users, retained users, rate and exclusion reason. The freshness comparison verifies processing delay and late-watermark counts by product and event type.

## Forecast governance

For each product, the workflow evaluates DAU, revenue and paid subscriptions with a seven-day seasonal-naive baseline over a 28-point holdout. The final-`first_open` event-time boundary prevents simulator follow-up from leaking into forecast history.

In the verified run:

- all three DAU baselines pass at **3.9%–5.9% MAPE**;
- all six revenue/subscription baselines are withheld at **25.6%–37.3% MAPE** under the unchanged 20% gate.

```text
model executed successfully != forecast approved for planning
```

## Metric and decision contracts

Metric definitions store numerator, denominator, grain, unit and version. Retention contracts additionally store cohort event, return event, horizon and exact-calendar-day return window. Freshness contracts store event/processing-time fields, allowed lateness, snapshot and backfill action. The watermark decision contract stores the candidate grid, hard budget, selection rule and chosen row.

Pricing decisions elsewhere in the workbench keep commercial evidence and customer-safety evidence separate. Revenue upside cannot mathematically compensate for a harmful customer state.

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
│   ├── validate_build.py
│   └── validate_reference_claims.py
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
python scripts/validate_reference_claims.py build/reference
pytest -q
```

Or run the existing local gate:

```bash
make check
```

## Generated reference evidence

The current build contains **25 portable CSV/JSON artifacts** hashed by `MANIFEST.json`, including the two v0.27 calibration artifacts. The GitHub Actions workflow artifact additionally includes `workbench.duckdb`.

## Reproducibility boundary

Current numerical claims must either be regenerated by the present workflow and checked in CI or explicitly labelled as preserved historical context. `results/risk_aware_design.csv` remains a preserved pre-v0.23 planning snapshot; it is not presented as a current regression target or production recommendation.

See [`docs/REPRODUCIBILITY.md`](docs/REPRODUCIBILITY.md), [`docs/LATE_ARRIVAL_GOVERNANCE.md`](docs/LATE_ARRIVAL_GOVERNANCE.md) and [`docs/WATERMARK_CALIBRATION.md`](docs/WATERMARK_CALIBRATION.md).
