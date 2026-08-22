# Product Analytics & Data Reliability Workbench

**Version:** v0.28  
**Stack:** Python · DuckDB · SQL · Pandas · NumPy · SciPy · Statsmodels · Pytest · GitHub Actions

A reproducible analytics workbench for a synthetic portfolio of subscription products. It is organised around one practical question:

> When a product KPI moves, can the team trust the number, explain the movement, and make a defensible decision using only evidence actually available at the reporting time?

The repository combines event certification, metric contracts, revenue reconciliation, point-in-time retention, forecast gates, experiment guardrails, processing-time freshness, watermark calibration, rolling SLA backtesting and evidence provenance in one auditable workflow.

All data and results are synthetic, controlled-fault outputs or explicitly labelled planning stress tests. Nothing here is presented as production-company performance.

## Verified v0.28 reference design

The deterministic reference uses `seed=2206`, `days=120`. v0.28 preserves the commercial, DAU and mature-retention truth of the prior releases, but tightens the freshness decision in two ways:

1. the late-event decision denominator is now point-in-time and candidate-specific: only events whose event date is on or before that candidate's watermark enter the SLA risk fraction;
2. the same 24/48/72/96-hour policy grid is replayed across nine weekly processing snapshots rather than trusted from one final snapshot.

| Check | Reference result |
|---|---:|
| Raw events | **276,249** |
| Rejected / certified rows | **589 / 275,660** |
| Raw revenue overstatement | **9.13%–10.96%** |
| Paid / first-open | **16.17%** |
| Paid / trial-start | **48.55%** |
| DAU forecasts approved | **3 / 3** |
| Revenue / subscription forecasts withheld | **6 / 6** |
| Unit + parity/calibration/backtest tests | **41 passed** in first v0.28 CI build |
| Portable artifacts in SHA-256 manifest | **29** |

The first v0.28 CI build passed the unit suite, 120-day reference build and generic build validator. It intentionally failed the old v0.27 pinned-claim gate because that gate still required the old reference version/summary field; the gate has now been rewritten for v0.28 and is revalidated on the final branch head before merge.

## v0.28: one snapshot is not enough to certify an SLA

v0.27 asked which watermark was shortest while satisfying four independent risk constraints at the 2026-04-30 processing snapshot. v0.28 keeps those exact thresholds and asks a harder question:

> Does the same candidate remain feasible when the reporting snapshot moves through time?

The hard risk budget is unchanged:

```text
late-event fraction among finalizable events <= 0.50%
revised finalized KPI-cell fraction          <= 1.00%
max |single revenue revision|                 <= £10
max |paid-subscription revision|              <= 1
```

There is no weighted score and the budget is not relaxed after seeing the backtest.

### Point-in-time denominator correction

For each candidate and processing snapshot:

```text
candidate watermark date
        |
        v
historical events with event_date <= watermark
        |
        +--> finalizable_events
        |
        `--> late-event fraction used by SLA decision
```

Events occurring after that candidate's watermark no longer inflate or dilute the decision denominator. The whole settled-stream late rate is still emitted as a diagnostic column, but it is not the policy constraint.

At the 2026-04-30 snapshot, this correction does **not** change the local choice:

| Candidate | Finalizable events | Point-in-time late fraction | Revised-cell fraction | Max revenue revision | Feasible? |
|---|---:|---:|---:|---:|---|
| 24h | 251,928 | **6.932%** | **1.214%** | £9.99 | No |
| 48h | 249,634 | **0.4951%** | **0.753%** | £7.99 | Yes |
| 72h | 247,364 | **0.4944%** | **0.380%** | £0.00 | Yes |
| 96h | 245,130 | **0.4814%** | **0.000%** | £0.00 | Yes |

So the single-snapshot rule still selects **48h** as the shortest feasible candidate.

## Rolling watermark backtest

v0.28 then evaluates the same four candidates at nine weekly processing snapshots from 2026-03-05 through 2026-04-30. Each window independently selects its shortest feasible candidate under the unchanged budget.

The observed per-window shortest choices are:

```text
72h, 72h, 72h, 96h, 48h, 48h, 48h, 48h, 48h
```

Aggregate stability is materially different from the single-snapshot view:

| Candidate | Feasible windows | Feasibility rate | Worst revised-cell fraction | Worst revenue revision | Stable in all windows? |
|---|---:|---:|---:|---:|---|
| 24h | 0 / 9 | 0.0% | 1.940% | £23.98 | No |
| 48h | 5 / 9 | 55.6% | **1.288%** | **£11.99** | No |
| 72h | 8 / 9 | 88.9% | 0.741% | **£11.99** | No |
| 96h | **9 / 9** | **100%** | 0.300% | £0.00 | **Yes** |

The stability decision is therefore:

```text
minimize finalization lag
subject to the original hard budget passing in every backtest window

selected stable SLA = 96h
budget relaxed after backtest = false
weighted score used = false
```

This deliberately produces a less fresh but more defensible policy than the final-snapshot result. v0.28 does **not** change the rule to 8/9 windows to preserve a 72-hour answer, and it does not raise the £10 revenue-revision threshold after observing a £11.99 breach.

Generated evidence:

```text
watermark_policy_grid.csv
watermark_policy_decision.json
watermark_rolling_grid.csv
watermark_rolling_windows.csv
watermark_stability_summary.csv
watermark_stability_decision.json
```

See [`docs/WATERMARK_CALIBRATION.md`](docs/WATERMARK_CALIBRATION.md) and [`docs/WATERMARK_STABILITY.md`](docs/WATERMARK_STABILITY.md).

## Why both 48h and 96h appear in the repository

They answer different operating questions:

```text
48h = shortest candidate feasible at the 2026-04-30 snapshot
96h = shortest candidate feasible in every declared rolling backtest window
```

A snapshot-local decision should not be relabelled as a stable SLA. The rolling policy is the stronger current operating recommendation for this synthetic reference, while the 48-hour row remains useful evidence of why a single end-of-study snapshot can be overconfident.

## Reference-claim drift is a CI failure

The validation layers are separated intentionally:

```text
pytest
  -> implementation behaviour

validate_build.py
  -> generic artifact/data invariants

validate_watermark_backtest.py
  -> calibration and rolling-selection accounting

validate_reference_claims.py
  -> pinned seed=2206, days=120 public claims
```

The pinned v0.28 claim gate checks that the single 2026-04-30 snapshot still selects 48h while the rolling stability decision selects 96h with candidate feasibility counts `0/9, 5/9, 8/9, 9/9`. If future code or synthetic data moves those claims, CI must fail until the public evidence is reviewed.

## v0.26 foundation: event time is not processing time

A trustworthy metric system distinguishes when an event happened from when the analytics platform received it:

```text
event_ts     = business/event time
ingested_at  = processing time
```

The generator uses a dedicated ingestion RNG, separate from commercial and activity randomness. Generated events include `ingested_at`; legacy inputs without it are interpreted as immediate arrivals. Explicit processing timestamps that are invalid or earlier than event time are rejected.

Under the 48-hour audit view at the Apr-30 snapshot, 24 events for nominally-final dates had not yet arrived and later settlement changes eight product-date-metric cells. Late events are reconciled through an idempotent keyed backfill rather than silently discarded.

See [`docs/LATE_ARRIVAL_GOVERNANCE.md`](docs/LATE_ARRIVAL_GOVERNANCE.md).

## Point-in-time retention remains explicit

Retention uses a declared `analysis_as_of` boundary. Only cohorts whose D7/D30 target date has matured enter the denominator; later cohorts remain visible as exclusions rather than being treated as churn.

| Product | Horizon | Eligible users | Excluded users | Eligible fraction | Retention among eligible |
|---|---:|---:|---:|---:|---:|
| File Transfer | D7 | 9,450 | 573 | **94.28%** | **19.56%** |
| File Transfer | D30 | 7,426 | 2,597 | **74.09%** | **6.36%** |
| Notes App | D7 | 8,643 | 525 | **94.27%** | **38.35%** |
| Notes App | D30 | 6,947 | 2,221 | **75.77%** | **21.88%** |
| Photo Editor | D7 | 10,352 | 637 | **94.20%** | **26.82%** |
| Photo Editor | D30 | 8,199 | 2,790 | **74.61%** | **11.20%** |

**Lower D30 eligibility is evidence maturity, not worse retention.**

## Explicit activity and DAU migration

DAU uses the v2 metric contract:

```text
DAU v1 (deprecated) = unique users with any certified event
DAU v2              = unique users with app_open
```

The verified legacy overstatement remains **5.27%** for File Transfer, **2.21%** for Notes App and **4.35%** for Photo Editor.

## Forecast governance

For each product, the workflow evaluates DAU, revenue and paid subscriptions with a seven-day seasonal-naive baseline over a 28-point holdout. The final-`first_open` event-time boundary prevents simulator follow-up from leaking into forecast history.

In the reference run:

- all three DAU baselines pass at **3.9%–5.9% MAPE**;
- all six revenue/subscription baselines are withheld at **25.6%–37.3% MAPE** under the unchanged 20% gate.

```text
model executed successfully != forecast approved for planning
```

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
      +----> point-in-time candidate calibration
      +----> rolling watermark backtest
      +----> revenue reconciliation
      |
      v
Gold daily metrics
      |
      +----> DAU v1/v2 migration
      +----> forecast evaluation
      +----> retention maturity ledger
      |
      +----> contracts + validators
      `----> SHA-256 manifest
```

## Python / DuckDB SQL parity

The `sql/` directory is tested code rather than illustrative syntax. CI independently executes and compares SQL with Python for Silver certification, Gold daily metrics, retention maturity and processing-latency summaries.

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
├── scripts/
│   ├── run_workbench.py
│   ├── validate_build.py
│   ├── validate_watermark_backtest.py
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
python scripts/validate_watermark_backtest.py build/reference
python scripts/validate_reference_claims.py build/reference
pytest -q
```

Or run the complete local gate:

```bash
make check
```

## Reproducibility boundary

Current numerical claims must either be regenerated by the present workflow and checked in CI or explicitly labelled as preserved historical context. The ingestion-delay distribution and risk budgets are synthetic/demo assumptions, not estimates of any real company's infrastructure. `results/risk_aware_design.csv` remains preserved historical planning context rather than a current production recommendation.

See [`docs/REPRODUCIBILITY.md`](docs/REPRODUCIBILITY.md), [`docs/LATE_ARRIVAL_GOVERNANCE.md`](docs/LATE_ARRIVAL_GOVERNANCE.md), [`docs/WATERMARK_CALIBRATION.md`](docs/WATERMARK_CALIBRATION.md) and [`docs/WATERMARK_STABILITY.md`](docs/WATERMARK_STABILITY.md).
