# Product Analytics & Data Reliability Workbench

**Version:** v0.36  
**Stack:** Python · DuckDB · SQL · Pandas · NumPy · SciPy · Statsmodels · openpyxl · Pytest · GitHub Actions

A reproducible analytics workbench for deciding when data, metrics, forecasts and experiments are trustworthy enough to support a business decision.

v0.36 deliberately combines two evidence lanes:

```text
controlled synthetic reference
    -> failure injection, point-in-time correctness, contract migration,
       forecasting, experiment guardrails and decision boundaries

public real-world reference
    -> external schema adaptation, source-quality evidence, metric semantics,
       frozen forecast portability and independent recomputation
```

The design principle is simple: **a technically successful calculation is not automatically an authorised decision input**.

## v0.36 headline: real-world portability

The external lane uses **UCI Online Retail II**, a public dataset of real transactions from a UK-based non-store online retailer covering 1 December 2009 to 9 December 2011 (DOI `10.24432/C5CG6D`, CC BY 4.0).

The workflow downloads the official source in GitHub Actions; the raw workbook is not committed to this repository. The accepted source is pinned by SHA-256 so an upstream replacement fails loudly before any public evidence is regenerated.

| Real-data check | Validated result |
|---|---:|
| Source transaction rows | **1,067,371** |
| Calendar days in daily metric layer | **739** |
| Purchase-line rows under declared contract | **1,041,670** |
| Missing CustomerID rows | **243,007** |
| Cancellation rows | **19,494** |
| Exact duplicate rows excluding generated source-row ID | **12,133** |
| Semantic drop-in replacements approved / withheld | **0 / 2** |
| Frozen forecast metrics approved / withheld | **0 / 4** |
| Real-data unit tests | **3 passed** |
| Full repository unit tests | **84 passed** |
| Compact manifested real-data artifacts | **8** |

### External data are allowed to disagree with the synthetic reference

The v0.35 forecast contract is reused **without retuning** after seeing UCI data: weekly seasonal-naive lag 7 vs a last-value benchmark, four rolling origins × seven-day horizon, MAPE/WAPE ≤20%, candidate WAPE no worse than benchmark, and interval coverage ≥85%.

All four real-data candidates beat the last-value benchmark on WAPE, yet all four are still withheld because at least one pre-existing absolute-accuracy gate fails:

| Metric | MAPE | Candidate WAPE | Last-value WAPE | Coverage | Decision |
|---|---:|---:|---:|---:|---|
| `revenue_gbp` | **25.28%** | **28.50%** | 45.18% | 85.7% | **WITHHOLD** |
| `orders` | **20.94%** | 15.31% | 37.35% | 89.3% | **WITHHOLD** |
| `units` | **26.20%** | **29.34%** | 46.55% | 92.9% | **WITHHOLD** |
| `active_customers` | **22.79%** | 17.03% | 37.34% | 92.9% | **WITHHOLD** |

`orders` is the clearest boundary case: **15.31% WAPE** and about **59% lower WAPE than the last-value benchmark** look encouraging, but MAPE is **20.94%**, just above the frozen 20% limit. The threshold is not relaxed post hoc.

### Real metric semantics are governed too

Two alternative definitions are evaluated as proposed *drop-in replacements*, not labelled intrinsically right or wrong:

| Replacement | Current value | Candidate value | Shift | Decision |
|---|---:|---:|---:|---|
| positive non-cancelled purchase revenue -> signed transaction ledger | £20.973m | £19.287m | **-8.04%** | **WITHHOLD** |
| purchasing-customer population -> any-transaction customer population | 5,878 | 5,942 | **+1.09%** | **WITHHOLD** |

A signed ledger that includes cancellations/returns can be useful, but an 8.04% movement means it cannot silently replace the published purchase-revenue metric under the same name. The customer definition is much closer but still crosses the declared 1% backward-compatibility tolerance.

The first real-data CI also found a portability bug that the synthetic generator had not exposed: a date with valid anonymous purchases but no identifiable CustomerID produced `NaN` after the customer-count join. The implementation was corrected to represent **0 identifiable active customers**, rather than weakening the test.

See [`docs/REAL_DATA_PORTABILITY.md`](docs/REAL_DATA_PORTABILITY.md).

## Controlled reference: hard decisions, not optimistic scores

The synthetic lane remains intentionally controlled so specific failure modes can be reproduced exactly.

### Contract and metric evolution

v0.35 separates structural compatibility, metric semantic safety and downstream decision stability:

| Proposal | Class | Producer compatible | Metric invariant | Forecast eligibility stable | Action |
|---|---|---:|---:|---:|---|
| add optional `country` | ADDITIVE | PASS | PASS | PASS | **APPROVE** |
| broaden DAU to any certified event | SEMANTIC | PASS | **FAIL** | PASS | **WITHHOLD** |
| rename required `event_id` -> `event_uuid` | BREAKING | **FAIL** | PASS | PASS | **WITHHOLD** |

The semantic case uses a **450 product-day shadow replay**. Broadening DAU moves aggregate DAU by +4.94%, +2.04% and +4.04% across the three synthetic products while paid/revenue controls remain unchanged. All three downstream DAU forecast eligibility states also remain unchanged. The migration is still withheld because stable downstream decisions cannot compensate for a materially changed KPI definition.

See [`docs/CONTRACT_EVOLUTION_GOVERNANCE.md`](docs/CONTRACT_EVOLUTION_GOVERNANCE.md).

### Forecast accuracy is not enough

The synthetic reference approves **2 / 9** forecast metrics. Its strongest counterexample is `photo_editor:dau`:

```text
weekly seasonal-naive WAPE = 3.92%
last-value benchmark WAPE   = 2.56%
absolute-accuracy gate      = PASS
benchmark gate              = FAIL
final decision              = WITHHOLD
```

A low standalone error therefore does not justify extra model structure when a simpler benchmark is better.

See [`docs/FORECAST_DECISIONING.md`](docs/FORECAST_DECISIONING.md).

### Positive revenue is not rollout authorisation

The deterministic 8,000-user pricing experiment produces:

```text
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

A downstream hypothetical launch scenario has **£102,762** counterfactual 30-day cohort revenue impact, but the failed experiment guardrail means **0 decision-authorised treated users** and no authorised incremental revenue.

See [`docs/EXPERIMENT_DECISIONING.md`](docs/EXPERIMENT_DECISIONING.md) and [`docs/IMPACT_PLANNING.md`](docs/IMPACT_PLANNING.md).

### Observed freshness is not statistical certification

Synthetic processing-time evidence deliberately separates:

```text
48h   shortest feasible candidate at the final snapshot
96h   shortest candidate feasible in all 9 rolling windows
none  candidate certified at 95% family-wise confidence
96h   only candidate whose current certification gap is evidence-depth-only
```

The uncertainty layer uses Bonferroni control over **72 simultaneous one-sided exact Clopper-Pearson bounds**. The 96h candidate is observationally stable but is not relabelled statistically certified.

See [`docs/WATERMARK_STABILITY.md`](docs/WATERMARK_STABILITY.md), [`docs/WATERMARK_UNCERTAINTY.md`](docs/WATERMARK_UNCERTAINTY.md) and [`docs/CERTIFICATION_EVIDENCE_PLANNING.md`](docs/CERTIFICATION_EVIDENCE_PLANNING.md).

## Validation architecture

The two lanes use separate evidence boundaries.

### Synthetic controlled lane

```text
pytest                         -> 84 total repository tests
build_reference.py             -> deterministic controlled reference
validate_build.py              -> generic build invariants
validate_forecast_plan.py      -> 252-point forecast reconstruction
validate_contract_migration.py -> 450-row replay + forecast comparisons + actions
validate_watermark_backtest.py -> point-in-time / rolling accounting
validate_uncertainty_certification.py
validate_evidence_plan.py
validate_pricing_experiment.py
validate_impact_plan.py
validate_reference_claims.py
validate_static_claim_ledger.py
```

The controlled reference contains **53 SHA-256-manifested portable artifacts**.

### Real-world UCI lane

```text
official UCI ZIP
  -> pinned archive/workbook SHA-256
  -> canonical adapter over both workbook sheets
  -> source-quality report
  -> source-specific metric contract
  -> 739-day daily metrics
  -> semantic replacement evidence
  -> frozen v0.35 forecast contract
  -> independent DuckDB/Python recomputation
  -> checked-in real-data claim ledger
```

`validate_real_retail_reference.py` re-extracts and reloads all **1,067,371 rows**, independently recomputes source-quality and daily metrics in DuckDB, then rebuilds semantic and forecast decisions. `validate_real_static_claims.py` binds the generated evidence to [`results/real_data_reference_summary.csv`](results/real_data_reference_summary.csv).

## Reproduce

Install once:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -e .
```

Run the deterministic controlled lane:

```bash
make check
```

Run the network-enabled real-data lane:

```bash
make real-check
```

The real-data command downloads the pinned UCI source. The source file itself is not added to Git.

## Claim boundaries

- UCI Online Retail II is public **real-world historical transaction data**; this repository is not a production deployment and does not claim access to a company's private systems.
- The UCI source exposes invoice/event time but **no separate ingestion timestamp**. v0.36 therefore does not claim real-data validation of late-arrival, watermark, backfill or processing-time SLA behaviour. Those remain controlled synthetic evidence.
- The 1% semantic tolerance is a declared governance threshold for this workbench, not a universal industry threshold.
- Forecast thresholds are intentionally frozen before the external evaluation; failed real-data gates are reported rather than tuned away.
- Synthetic acquisition, delays, migration proposals, experiments and launch scenarios remain explicitly synthetic/reference assumptions.

The central progression is:

```text
trust the source
-> define the metric explicitly
-> preserve point-in-time boundaries
-> benchmark forecasts honestly
-> gate experiments non-compensatorily
-> distinguish counterfactual impact from authorised action
-> reproduce the claims independently
```
