# Product Analytics & Data Reliability Workbench

**Version:** v0.38  
**Stack:** Python · DuckDB · SQL · Pandas · NumPy · SciPy · Statsmodels · Parquet · Pytest · GitHub Actions

A reproducible analytics workbench for deciding when data, metrics, forecasts and experiments are trustworthy enough to support a business decision — and for exposing validated metrics through a bounded, versioned consumer contract without giving up provenance, recovery or performance discipline.

The repository now has four complementary evidence layers:

```text
controlled synthetic evidence
    -> failure injection, point-in-time correctness, contract migration,
       forecasting, experiment guardrails and decision boundaries

public real-world evidence
    -> external schema adaptation, source quality, metric semantics,
       frozen forecast portability and independent recomputation

real-world operational evidence
    -> immutable partitions, incremental processing, idempotency,
       interruption recovery, targeted repair and performance diagnosis

consumer data-product evidence
    -> versioned metric catalog, bounded historical queries, zero-fill,
       selected-partition provenance, integrity-before-serve and JSON/CSV outputs
```

The design principle is unchanged: **a technically successful calculation is not automatically a trustworthy, operationally efficient or safely consumable decision input**.

## v0.38 headline: a versioned reporting data product

v0.38 turns the validated v0.37 real-data metric store into a small consumer-facing data product rather than adding another model or dashboard. The implementation is deliberately framework-free: Python defines the stable contract, DuckDB reads only relevant metric partitions, and a CLI exposes JSON or CSV. A future network transport can change without redefining metric semantics.

Five allowlisted daily metrics are available:

- `revenue_gbp`
- `orders`
- `units`
- `purchase_lines`
- `active_customers`

Every JSON response carries the schema/data-product versions, normalised query, historical availability, selected metric-partition provenance, row count, deterministic response SHA-256 and data rows. Missing calendar days are explicitly zero-filled instead of being ambiguous missing rows.

| v0.38 consumer check | Validated result |
|---|---:|
| Reporting schema | **1.0** |
| Allowlisted daily metrics | **5** |
| Backing metric partitions | **25** |
| Historical availability | **2009-12-01 → 2011-12-09** |
| Maximum query span | **366 days** |
| Reference query | **7 days** |
| Metric-value partitions selected for reference query | **1 / 25** |
| Metric-partition selection reduction | **96%** |
| Reference response vs validated daily layer | **exact match** |
| Cross-month reference query | **exactly 2 partitions** |
| Unknown metric | **rejected** |
| Over-wide / invalid range | **rejected** |
| Deliberately corrupted selected partition | **rejected before serve** |
| JSON / CSV CLI smoke tests | **PASS** |
| Full repository tests | **93 passed** |

The 96% figure is deliberately narrow: it is a reduction in **metric-value partition selection** for the seven-day reference query relative to reading all 25 monthly metric partitions. Store initialisation separately integrity-checks and reads the first/last boundary partitions to establish historical availability. It is not claimed as a 96% end-to-end latency or source-row reduction.

### Integrity must happen before the query engine reads data

The first v0.38 CI attempt exposed an ordering flaw. A test deliberately corrupted a boundary Parquet file; the store tried to read that file with DuckDB to determine date bounds before validating its SHA-256, so DuckDB raised its own `InvalidInputException` before the reporting contract could fail closed.

The implementation was changed so boundary partitions are checked **before any DuckDB read**:

```text
canonical source manifest
        +
durable incremental state
        +
metric file existence / SHA-256
        ↓
all bindings agree
        ↓
DuckDB may read the partition
```

The next CI run correctly raised `ReportingContractError` during store construction. A separate real-data tamper case corrupts the middle `2010-12` metric partition and confirms it is rejected when selected by a query. This keeps integrity checking on both the metadata-boundary and normal query paths.

### Consumer requests are intentionally bounded

The interface rejects unknown or duplicate metric names, reversed ranges, dates outside the available historical store and requests longer than 366 days. A seven-day December 2010 request selects the single `2010-12` metric partition for metric values; a query crossing the November/December boundary selects exactly two.

The reporting layer reuses already validated v0.37 metric partitions. It does **not** reparse the 45 MB XLSX or rescan the 1,067,371-row canonical source merely to serve a consumer request.

See [`docs/REPORTING_DATA_PRODUCT.md`](docs/REPORTING_DATA_PRODUCT.md).

## v0.37: incremental processing, recovery and performance

v0.37 keeps the pinned **UCI Online Retail II** source used in v0.36 — **1,067,371 real historical transaction rows** — but stops treating every run as a full rebuild.

The source is canonicalised once into **25 immutable monthly Parquet partitions** with row counts, byte sizes and SHA-256 provenance. Durable state is committed after each successful metric partition.

```text
pinned UCI XLSX
    ↓ one-time canonicalisation
25 month-partitioned Parquet files + SHA-256 manifest
    ↓
partition state / derived-output hashes
    ↓
process only missing, revised or invalidated partitions
    ↓
exact reconciliation to clean full rebuild
```

| v0.37 operational check | Validated result |
|---|---:|
| Real source rows | **1,067,371** |
| Canonical month partitions | **25** |
| Canonical Parquet bytes | **9,806,373** |
| Source workbook bytes | 45,622,278 |
| Full vs incremental daily metrics | **exact match** |
| Idempotent no-op source rows scanned | **0** |
| Large source partitions re-hashed in normal no-op | **0** |
| Simulated interruption point | 7 completed partitions |
| Durable rows reused after restart | **257,045** |
| Restart partitions skipped | **7** |
| Targeted repair partition | `2010-12` |
| Targeted repair source rows scanned | **65,004** |
| Repair scan reduction vs full source | **93.91%** |
| Repaired output hashes restored | **exact match** |
| Explicit full source integrity audit | **25 / 25 SHA-verified** |
| v0.37 release tests | **88 passed** |

The checked-in v0.37 claim ledger pins the deterministic work counts above. It deliberately does **not** pin shared-runner wall-clock timings.

### Why performance was slow

The v0.37 investigation separated two different problems.

**1. Source-format bottleneck.** The official source is XLSX. GitHub Actions repeatedly shows that decompressing/parsing the workbook and normalising 1.07M rows dominates first load, while a clean DuckDB aggregation over canonical Parquet is tiny by comparison. The source format, not analytical SQL, is the main first-load bottleneck.

**2. Initial incremental implementation overhead.** The first implementation opened a DuckDB connection per monthly partition and scanned each changed partition twice: once for `COUNT(*)`, then again for aggregation. It was correct but wasteful. The implementation now uses one DuckDB connection per run, manifest-certified row counts and one aggregation scan per changed partition.

Wall-clock differences across shared GitHub runners remain diagnostic only; deterministic work avoided is the performance contract.

| Operation | Source rows scanned | Reduction vs 1,067,371-row full scan |
|---|---:|---:|
| Full rebuild baseline | 1,067,371 | 0% |
| Idempotent no-op | **0** | **100%** |
| Targeted `2010-12` repair | **65,004** | **93.91%** |
| Restart after seven durable partitions | **810,326** | **24.08%** |

This avoids a misleading claim that partitioning must always beat a single vectorised full scan. On this local 1M-row Parquet dataset, a clean full DuckDB aggregation is already extremely fast; incremental processing matters because unchanged/repaired/restarted runs do not repeat irrelevant source work and because the state is recoverable and auditable.

See [`docs/INCREMENTAL_RECOVERY_PERFORMANCE.md`](docs/INCREMENTAL_RECOVERY_PERFORMANCE.md).

## v0.36: real-world portability

The external lane uses **UCI Online Retail II**, real historical transactions from a UK-based non-store online retailer covering 1 December 2009 to 9 December 2011 (DOI `10.24432/C5CG6D`, CC BY 4.0).

The raw workbook is not committed. GitHub Actions downloads the official source, verifies the pinned archive/workbook SHA-256 values, adapts both workbook sheets and independently rebuilds the evidence.

| Real-data check | Validated result |
|---|---:|
| Source rows | **1,067,371** |
| Calendar days | **739** |
| Valid purchase-line rows | **1,041,670** |
| Missing CustomerID rows | **243,007** |
| Cancellation rows | **19,494** |
| Exact duplicate rows excluding generated source-row ID | **12,133** |
| Semantic replacements approved / withheld | **0 / 2** |
| Frozen forecast metrics approved / withheld | **0 / 4** |

The real data exposed a portability bug not present in the synthetic generator: a date with valid anonymous purchases but no identifiable CustomerID produced `NaN` after the customer-count join. The implementation was fixed to represent **0 identifiable active customers** rather than weakening the test.

### Frozen forecast rules are allowed to fail

The v0.35 forecast contract is reused without retuning after seeing the real data.

| Metric | MAPE | WAPE | Last-value WAPE | Decision |
|---|---:|---:|---:|---|
| `revenue_gbp` | 25.28% | 28.50% | 45.18% | **WITHHOLD** |
| `orders` | **20.94%** | **15.31%** | 37.35% | **WITHHOLD** |
| `units` | 26.20% | 29.34% | 46.55% | **WITHHOLD** |
| `active_customers` | 22.79% | 17.03% | 37.34% | **WITHHOLD** |

`orders` is the useful boundary case: candidate WAPE is far better than the last-value benchmark, but MAPE is **20.94%**, just above the frozen 20% gate. The threshold is not relaxed after seeing the result.

### Real metric semantics are governed too

Two plausible alternative definitions fail as silent drop-in replacements:

| Proposed replacement | Shift | Decision |
|---|---:|---|
| positive non-cancelled purchase revenue → signed transaction ledger | **-8.04%** | **WITHHOLD** |
| purchasing-customer population → any-transaction customer population | **+1.09%** | **WITHHOLD** |

The alternative metrics may be useful under new names; the result only says they are not backward-compatible replacements within the declared 1% semantic tolerance.

See [`docs/REAL_DATA_PORTABILITY.md`](docs/REAL_DATA_PORTABILITY.md).

## Controlled evidence: reproduce hard decision boundaries

Synthetic data remain useful where the public real source lacks required fields or where a controlled counterexample is the point of the test.

### Contract evolution

v0.35 separates producer compatibility, metric semantic safety and downstream decision stability.

| Proposal | Class | Producer compatible | Metric invariant | Forecast stable | Action |
|---|---|---:|---:|---:|---|
| add optional `country` | ADDITIVE | PASS | PASS | PASS | **APPROVE** |
| broaden DAU to any certified event | SEMANTIC | PASS | **FAIL** | PASS | **WITHHOLD** |
| rename required `event_id` → `event_uuid` | BREAKING | **FAIL** | PASS | PASS | **WITHHOLD** |

The semantic case uses a **450 product-day shadow replay**. Aggregate DAU moves by +4.94%, +2.04% and +4.04% while all three downstream DAU forecast eligibility states remain unchanged. Stable downstream decisions do not compensate for a materially changed KPI definition.

See [`docs/CONTRACT_EVOLUTION_GOVERNANCE.md`](docs/CONTRACT_EVOLUTION_GOVERNANCE.md).

### Forecast accuracy is not enough

The synthetic reference approves **2 / 9** forecast metrics. `photo_editor:dau` has only **3.92% WAPE**, but the last-value benchmark has **2.56%**, so the candidate is **WITHHOLD** despite low standalone error.

See [`docs/FORECAST_DECISIONING.md`](docs/FORECAST_DECISIONING.md).

### Positive revenue is not rollout authorisation

The controlled 8,000-user pricing experiment estimates **+£0.6851/user/30d** with a positive 95% CI, but its paid-conversion guardrail fails. The experiment remains **HOLD**; a hypothetical **£102,762** cohort revenue impact remains counterfactual-only, with **0 decision-authorised treated users**.

See [`docs/EXPERIMENT_DECISIONING.md`](docs/EXPERIMENT_DECISIONING.md) and [`docs/IMPACT_PLANNING.md`](docs/IMPACT_PLANNING.md).

### Observed freshness is not statistical certification

Synthetic processing-time evidence separates a 48h final-snapshot choice, a 96h candidate stable across nine rolling windows, and the stronger statement that **no candidate is certified at 95% family-wise confidence**. The public UCI source has no ingestion timestamp, so this evidence remains explicitly synthetic.

See [`docs/WATERMARK_STABILITY.md`](docs/WATERMARK_STABILITY.md), [`docs/WATERMARK_UNCERTAINTY.md`](docs/WATERMARK_UNCERTAINTY.md) and [`docs/CERTIFICATION_EVIDENCE_PLANNING.md`](docs/CERTIFICATION_EVIDENCE_PLANNING.md).

## Validation architecture

Three independent CI lanes protect different evidence boundaries; the operational lane now also validates the consumer contract.

```text
controlled synthetic lane
  pytest (93 repository tests)
  → deterministic reference build
  → forecast / migration / watermark / uncertainty validators
  → experiment / impact validators
  → pinned and static claim validators

real-data portability lane
  official pinned UCI download
  → source adapter / quality / metrics
  → semantic and frozen forecast evidence
  → independent DuckDB/Python recomputation
  → checked-in real-data claim ledger

incremental operational + reporting lane
  official pinned UCI download
  → canonical 25-partition Parquet snapshot
  → interruption / no-op / repair scenarios
  → independent full rebuild parity + source/output SHA audit
  → versioned five-metric reporting contract
  → 1/25 and cross-month partition-pruning checks
  → tamper rejection + independent response reconciliation
  → JSON / CSV consumer smoke tests
```

## Reproduce

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -e .

make check             # controlled deterministic lane
make real-check        # network-enabled UCI portability lane
make incremental-check # network-enabled v0.38 recovery/performance/reporting lane
```

After `make incremental-check`, query the data product directly:

```bash
python scripts/query_retail_metrics.py \
  --incremental-dir build/incremental-retail \
  --start 2010-12-01 \
  --end 2010-12-07 \
  --metrics revenue_gbp,orders,active_customers \
  --format json
```

## Claim boundaries

- UCI Online Retail II is public real-world historical transaction data; this repository is not a production deployment and does not claim access to a company's private systems.
- `InvoiceDate` is event time, **not ingestion time**. Real-data late-arrival, watermark, processing-time SLA and point-in-time/as-of reconstruction are therefore not claimed.
- The reporting layer is a local Python/CLI data-product boundary, not a deployed network service or production availability/latency claim.
- The v0.38 **96%** figure is metric-partition-selection reduction for the pinned seven-day query, not source-row reduction and not a latency speedup.
- The 1% semantic tolerance is a declared workbench governance threshold, not a universal industry threshold.
- Forecast thresholds were frozen before the external evaluation; failed real-data gates are reported rather than tuned away.
- Shared GitHub-runner timings are diagnostic only. Public performance claims use deterministic rows/partitions selected or scanned and exact parity.
- The operational evidence is single-node DuckDB/Parquet; it does not claim distributed-system, object-store or production-network benchmarks.

The progression is:

```text
trust the source
→ define the metric explicitly
→ preserve point-in-time semantics where the source supports them
→ test decisions without leakage
→ validate on external real data
→ update incrementally without losing reproducibility
→ recover and repair without silently changing the answer
→ expose validated metrics through a bounded, versioned consumer contract
```
