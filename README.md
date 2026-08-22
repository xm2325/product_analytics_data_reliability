# Product Analytics & Data Reliability Workbench

**Version:** v0.23  
**Stack:** Python · DuckDB · SQL · Pandas · NumPy · SciPy · Statsmodels · Pytest · GitHub Actions

A reproducible analytics workbench for a synthetic portfolio of subscription products. It is organised around one practical question:

> When a product KPI moves, can the team trust the number, explain the movement, and make a defensible decision?

The repository combines event certification, metric contracts, revenue reconciliation, forecasting gates, experiment guardrails and risk-aware evidence planning in one auditable workflow.

All data and results are synthetic, controlled-fault outputs or explicitly labelled planning stress tests. Nothing in this repository is presented as production-company performance.

## v0.23 at a glance

The current public workflow now treats failed data as evidence rather than silently dropping it:

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
      +----> forecast_evaluations
      +----> metric/event contracts
      +----> SHA-256 manifest
```

The CI pipeline runs unit tests, builds a 120-day deterministic reference dataset, validates the generated evidence, and uploads the resulting CSV/JSON/DuckDB bundle as a workflow artifact.

## What the current workflow demonstrates

| Capability | Current implementation |
|---|---|
| Data certification | Duplicate IDs, missing identities, invalid timestamps/revenue, unknown products/events and revenue-on-non-purchase rows are rejected with row-level reasons. |
| Revenue reconciliation | Raw purchase revenue is compared with certified purchase revenue by product; controlled duplicate faults remain observable rather than entering Gold metrics. |
| Metric semantics | Conversion metrics keep numerator, denominator, grain, unit and version as machine-readable contracts. |
| Forecast governance | A seasonal-naive rolling evaluation is fitted for DAU, revenue and paid subscriptions per product; forecasts are explicitly approved or withheld by a declared gate. |
| Safe recovery | Backfills use replacement semantics so replaying the same correction is a no-op. |
| Experiment governance | Revenue evidence and paid-conversion harm clearance are separate, non-compensatory rollout gates. |
| Evidence integrity | Portable outputs are SHA-256 hashed and independently validated after generation. |

## Repository structure

```text
.
├── src/product_analytics/
│   ├── config.py             # synthetic product configuration
│   ├── generator.py          # deterministic event generation + controlled faults
│   ├── contracts.py          # machine-readable event contract
│   ├── quality.py            # certification, rejects and reconciliation
│   ├── metrics.py            # metric contracts and KPI calculations
│   ├── forecasting.py        # holdout forecast evaluation and planning gate
│   ├── experiments.py        # experiment estimands and non-compensatory guardrails
│   ├── risk_design.py        # allocation / evidence-planning primitives
│   ├── provenance.py         # SHA-256 artifact manifest
│   └── pipeline.py           # Bronze -> Silver -> Gold orchestration
├── sql/
├── scripts/
│   ├── run_workbench.py
│   └── validate_build.py
├── tests/
├── results/                  # compact preserved reference/planning snapshots
├── docs/
│   ├── METRIC_CONTRACTS.md
│   ├── RESULTS.md
│   └── REPRODUCIBILITY.md
└── .github/workflows/ci.yml
```

## Data reliability design

### Bronze: preserve what arrived

Bronze keeps the raw synthetic event stream, including deliberately injected duplicate purchase rows and identity faults. Bad data is not rewritten in place.

### Silver: certify and explain rejection

Certification checks:

- duplicate `event_id`;
- missing or blank `user_id`;
- unparseable timestamp;
- non-numeric or negative revenue;
- unknown product;
- unknown event type;
- non-zero revenue on a non-purchase event.

A row can violate several rules. `rejected_events.csv` therefore stores a semicolon-separated `reject_reason`, preserving the complete failure evidence.

The accounting invariant is enforced in the build validator:

```text
rows_raw = rows_certified + rows_rejected
```

### Gold: calculate only from certified events

Gold metrics consume Silver rows only. The workbench keeps validation evidence and business metrics separate so a bad record remains inspectable without silently affecting a certified KPI.

## Metric contracts

Metric names are not definitions. The reference build writes `metric_contracts.json` and `event_contract.json`.

For example, these are intentionally different metrics:

```text
paid_conversion_from_first_open
paid_conversion_from_trial_start
```

Both may be correct because they answer different denominator questions. The contract stores numerator, denominator, grain, unit and version rather than relying on a dashboard label.

## Forecast gate

For each product, the workflow evaluates:

- DAU;
- revenue;
- paid subscriptions.

The current compact implementation uses a seven-day seasonal-naive baseline over a 28-point rolling holdout. A forecast is withheld if there are too few holdout points, MAPE is not estimable, or MAPE exceeds the declared threshold.

The distinction is deliberate:

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

`results/risk_aware_design.csv` preserves a planning snapshot from the earlier risk-design study, including the 20/80 higher-price allocation example. The compact v0.23 package retains the allocation mathematics and constraint objects, but not the entire historical Monte Carlo portfolio-risk engine that produced every tail-risk quantity.

Therefore this result is explicitly a **preserved planning snapshot**, not a current-workflow regression target or a production recommendation. See [`docs/REPRODUCIBILITY.md`](docs/REPRODUCIBILITY.md).

This distinction is intentional: documentation should never be more reproducible than the code that supports it.

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

A successful build contains:

```text
bronze_events.csv
rejected_events.csv
silver_events.csv
gold_daily_metrics.csv
revenue_reconciliation.csv
forecast_evaluations.csv
quality_report.json
metric_contracts.json
event_contract.json
reference_summary.json
MANIFEST.json
workbench.duckdb
```

`MANIFEST.json` stores file size and SHA-256 for the portable CSV/JSON evidence. `scripts/validate_build.py` verifies the hashes plus semantic invariants such as row accounting, reject reasons, product coverage and forecast/contract sets.

## Reproducibility boundary

The repository intentionally separates:

1. **current reproducible evidence** generated and checked by v0.23; and
2. **preserved planning snapshots** retained for methodological context.

See [`docs/REPRODUCIBILITY.md`](docs/REPRODUCIBILITY.md) for the exact rule.

## Development

```bash
make install
make check
```

Changes to certification rules, metric definitions, forecast gates or experiment constraints should include tests. Numerical README claims should either be regenerated by the current workflow or explicitly labelled as preserved snapshots.
