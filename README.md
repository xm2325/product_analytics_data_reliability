# Product Analytics & Data Reliability Workbench

**Version:** v0.40  
**Stack:** Python · DuckDB · SQL · Pandas · NumPy · SciPy · Statsmodels · Parquet · Pytest · GitHub Actions

A reproducible analytics workbench for deciding when data, metrics, forecasts and experiments are trustworthy enough to support a business decision — and for exposing validated metrics through a bounded consumer interface that remains reproducible as data, contracts and concurrent consumers evolve.

The repository has six complementary evidence layers:

```text
controlled synthetic evidence
    -> failure injection, point-in-time correctness, metric migration,
       forecasting, experiment guardrails and decision boundaries

public real-world evidence
    -> external schema adaptation, source quality, metric semantics,
       frozen forecast portability and independent recomputation

real-world operational evidence
    -> immutable partitions, incremental processing, idempotency,
       interruption recovery, targeted repair and work diagnosis

consumer data-product evidence
    -> bounded historical queries, metric catalogue, zero-fill,
       provenance, integrity-before-serve and JSON/CSV outputs

consumer contract-evolution evidence
    -> explicit schema negotiation, field-level compatibility classification,
       golden real-data responses and breaking-change gates

multi-consumer execution evidence
    -> request-local query engines, serial/concurrent exact parity,
       deterministic work accounting and failure isolation
```

The design principle is unchanged: **a calculation is not trustworthy merely because it ran successfully, and an interface is not safely scalable merely because it serves one correct request.**

## v0.40 headline: concurrent consumers must not change the answer

v0.40 keeps the v0.39 response schemas and metric semantics unchanged, but strengthens the execution boundary. The reporting store no longer reuses one mutable DuckDB connection across consumer queries. Immutable manifest/state metadata are shared; **every query creates and closes its own ephemeral DuckDB connection**.

The real reference workload runs on the same pinned **1,067,371-row UCI Online Retail II** source and 25-partition metric store used by v0.37–v0.39.

| v0.40 workload-isolation check | Validated result |
|---|---:|
| Data-product version | **0.40.0** |
| Default / latest JSON schema | **1.0 / 1.1** |
| Valid requests / consumers | **12 / 12** |
| Concurrent workers | **8** |
| Mixed workload requests | **15** |
| Injected invalid consumers | **3** |
| Intended failures isolated | **3 / 3** |
| Aggregate metric partitions selected | **27** |
| Aggregate selected metric files SHA-verified | **27** |
| Unique metric partitions touched | **16** |
| Aggregate response rows | **652** |
| Serial vs concurrent compact results | **exact parity** |
| Serial vs concurrent workload digest | **exact parity** |
| Healthy results preserved inside mixed workload | **PASS** |
| Healthy results preserved after failure batch | **PASS** |
| Parallel consumers on the same hot window | **6** |
| Unique full-payload hashes across those six | **1** |
| Matched schema 1.0/1.1 core response hash | **exact parity** |
| Operational focused tests | **17 passed** |
| Full repository tests | **101 passed** |

The deterministic workload fingerprint is:

```text
ef1adcc2dc091ad9ad00c16175ea7b38c8f6fec084c4c1700c6c50c127376e7e
```

### Why not put a lock around one shared connection?

A lock would make one mutable query engine safe by serialising access, but it would not create a clean consumer-isolation boundary. v0.40 instead keeps the store metadata immutable and request-independent while moving DuckDB query execution into request-local connections:

```text
canonical manifest + durable state + metric partitions
                      ↓
               immutable store
                      ↓
        ┌─────────────┼─────────────┐
        ↓             ↓             ↓
   consumer A     consumer B     consumer C
   DuckDB conn    DuckDB conn    DuckDB conn
        ↓             ↓             ↓
      close          close          close
```

The six repeated hot-window consumers therefore read the same declared data, return one identical full-payload hash and do not share query-engine state.

### A bad consumer must not poison healthy consumers

The mixed 15-request workload adds three deliberately invalid requests to the 12 valid requests:

- unknown metric;
- unsupported schema `2.0`;
- duplicate metric name.

All three fail through `ReportingContractError`. Every healthy request in the same concurrent batch remains exactly equal to its serial baseline, including response payload hash, query/data response SHA, selected partitions and returned rows. Replaying all healthy requests after the failure batch also reproduces the same baseline.

The independent validator does not import the workload harness. It constructs its own serial and threaded replays, reconciles successful responses back to `incremental_daily_metrics.csv`, recomputes response hashes, recomputes work accounting and verifies the exact failure set.

### Performance claim boundary

v0.40 deliberately has **no QPS, latency, throughput or speedup gate**. Shared GitHub runners are unsuitable evidence for a stable capacity claim. The public contract is result isolation plus deterministic work accounting: 12 valid requests selected 27 metric partitions in aggregate, returned 652 rows and produced the same workload digest under serial and 8-worker concurrent execution.

This remains a **single-node DuckDB/Parquet reference**, not a deployed network service, distributed database, tenant-quota system or production concurrency SLA.

See [`docs/WORKLOAD_ISOLATION.md`](docs/WORKLOAD_ISOLATION.md).

## v0.39: evolve the interface without silently migrating consumers

v0.39 separates the data-product release version from the consumer response schema. Existing/unversioned JSON consumers remain on schema **1.0**; schema **1.1** is explicit opt-in and adds only a top-level `contract` metadata object.

The same seven-day real-data query under schemas 1.0 and 1.1 preserves the query payload, metric rows, query/data response SHA and deterministic partition work exactly. Three governed migration proposals demonstrate one additive **APPROVE** and two breaking **WITHHOLD** decisions:

| Proposal | Classification | Decision |
|---|---|---|
| add negotiated `contract` metadata | ADDITIVE | **APPROVE** |
| rename `row_count` → `rows` | BREAKING | **WITHHOLD** |
| change `orders` integer → float | BREAKING | **WITHHOLD** |

Additive does not mean every possible parser accepts unknown fields; a strict existing consumer can continue requesting schema 1.0. No production support-lifetime or deprecation SLA is claimed.

See [`docs/CONSUMER_CONTRACT_EVOLUTION.md`](docs/CONSUMER_CONTRACT_EVOLUTION.md).

## v0.38: bounded reporting data product

Five allowlisted daily metrics are exposed through a framework-independent Python interface and JSON/CSV CLI:

- `revenue_gbp`
- `orders`
- `units`
- `purchase_lines`
- `active_customers`

The reporting store covers **2009-12-01 through 2011-12-09**, limits a request to **366 days**, zero-fills missing calendar days and SHA-verifies selected metric partitions before serving them. The pinned seven-day query selects **1 of 25** monthly metric partitions for metric values — a **96% partition-selection reduction**, not a latency claim — and exactly reconciles to the validated daily layer. A cross-month query selects exactly two partitions; unknown, over-wide and tampered requests fail closed.

See [`docs/REPORTING_DATA_PRODUCT.md`](docs/REPORTING_DATA_PRODUCT.md).

## v0.37: incremental recovery and deterministic work reduction

The UCI source is canonicalised into **25 immutable monthly Parquet partitions** with row counts and SHA-256 provenance. Durable state allows unchanged, interrupted and damaged runs to avoid irrelevant work while still reconciling to a clean rebuild.

| Operational check | Validated result |
|---|---:|
| Real source rows | **1,067,371** |
| Full vs incremental metrics | **exact match** |
| Idempotent no-op source rows scanned | **0** |
| Restart partitions skipped | **7** |
| Durable rows reused after restart | **257,045** |
| Targeted repair partition | `2010-12` |
| Targeted repair source rows scanned | **65,004** |
| Repair scan reduction vs full source | **93.91%** |
| Repaired output hashes | **exact match** |
| Full source integrity audit | **25 / 25 SHA-verified** |

The main first-load bottleneck is XLSX decompression/XML parsing and canonical type normalisation. Shared-runner timings remain diagnostic; stable performance claims use deterministic rows/partitions selected or scanned.

See [`docs/INCREMENTAL_RECOVERY_PERFORMANCE.md`](docs/INCREMENTAL_RECOVERY_PERFORMANCE.md).

## v0.36: external real-world portability

The external lane uses **UCI Online Retail II**, public real historical transactions from a UK-based non-store online retailer (DOI `10.24432/C5CG6D`, CC BY 4.0). GitHub Actions downloads the official source, verifies pinned archive/workbook SHA-256 values and independently reconstructs the evidence.

Key observed facts include **1,067,371 source rows**, **739 calendar days**, **1,041,670 valid purchase-line rows**, **243,007 missing CustomerID rows**, **19,494 cancellation rows** and **12,133 exact duplicates** excluding the generated source-row ID.

Real data is allowed to fail frozen rules. All four external forecast series are withheld under the pre-existing forecasting contract; `orders`, for example, has **15.31% WAPE** but **20.94% MAPE**, just above the frozen 20% gate. Two plausible metric replacements are also withheld as silent drop-ins because signed transaction value changes purchase revenue by **-8.04%** and the any-transaction customer population changes the purchasing-customer population by **+1.09%** against the declared 1% semantic tolerance.

See [`docs/REAL_DATA_PORTABILITY.md`](docs/REAL_DATA_PORTABILITY.md).

## Controlled decision evidence

Synthetic evidence is retained where the public source lacks the fields needed for controlled counterexamples.

### Metric and producer evolution

v0.35 performs a **450 product-day shadow replay**. An optional `country` field is approved, while a required `event_id → event_uuid` rename and a DAU semantic broadening are withheld. The semantic candidate changes aggregate DAU by up to **+4.94%** even though downstream forecast eligibility is unchanged, proving that stable downstream decisions do not compensate for a changed KPI definition.

### Forecast decisioning

The controlled forecast reference evaluates four rolling origins × seven-day horizons. `photo_editor:dau` has only **3.92% WAPE**, but the simpler last-value benchmark has **2.56%**, so the candidate remains withheld. Forecast accuracy alone is not eligibility.

### Experiment and impact decisioning

The 8,000-user pricing experiment estimates **+£0.6851/user/30d** with a positive 95% confidence interval, but its paid-conversion guardrail fails. The experiment remains **HOLD**; the hypothetical **£102,762** cohort revenue scenario remains counterfactual-only with **0 decision-authorised treated users**.

### Freshness uncertainty

Controlled processing-time evidence distinguishes an observed stable watermark choice from statistical certification. A 96h candidate is stable across nine rolling windows, but **no candidate is certified at 95% family-wise confidence** under the declared model. The real UCI source has invoice/event time but no independent ingestion timestamp, so no real-data watermark/as-of claim is fabricated.

## Validation architecture

Three CI lanes protect distinct evidence boundaries:

```text
controlled deterministic lane
  pytest (101 repository tests)
  → reference build
  → forecast / migration / watermark / uncertainty validators
  → experiment / impact validators
  → pinned and static claim validators

real-data portability lane
  official pinned UCI download
  → source adapter / quality / metrics
  → semantic and frozen forecast evidence
  → independent DuckDB/Python recomputation
  → checked-in real-data claim ledger

operational consumer lane
  official pinned UCI download
  → 25-partition canonical store
  → no-op / interruption / repair evidence
  → bounded reporting + integrity-before-serve
  → schema 1.0 default / explicit 1.1 negotiation
  → request-local DuckDB execution
  → serial vs 8-worker concurrent exact replay
  → mixed invalid-consumer failure isolation
  → independent workload recomputation
  → deterministic workload claim ledger
```

## Reproduce

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -e .

make check             # controlled deterministic lane
make real-check        # network-enabled external UCI lane
make incremental-check # network-enabled recovery/reporting/contract/workload lane
```

A reporting query can be executed directly:

```bash
python scripts/query_retail_metrics.py \
  --incremental-dir build/incremental-retail \
  --start 2010-12-01 \
  --end 2010-12-07 \
  --metrics revenue_gbp,orders,active_customers \
  --format json \
  --schema-version 1.1
```

## Claim boundaries

- UCI Online Retail II is public real-world historical data; this repository is not a production deployment and does not claim access to private company systems.
- `InvoiceDate` is event time, not ingestion time. Real-data late-arrival, watermark, processing-time SLA and point-in-time/as-of reconstruction are not claimed.
- The reporting layer is a local Python/CLI data-product boundary, not a deployed network service.
- Schema 1.1 being additive does not imply universal parser compatibility; schema 1.0 remains available through explicit negotiation.
- v0.40 proves request-local query execution and deterministic concurrent replay on one process / one node; it does not prove production QPS, tail latency, distributed isolation, fairness or capacity.
- The 96% reporting figure is metric-partition-selection reduction for one pinned query, not source-row reduction or latency speedup.
- The 1% semantic tolerance is a declared workbench governance threshold, not a universal industry threshold.
- Forecast thresholds were frozen before external evaluation; failed gates are reported rather than retuned away.
- Shared GitHub-runner timings are diagnostic only. Public operational claims use deterministic rows/partitions/hashes and exact parity.

The progression is:

```text
trust the source
→ define metrics explicitly
→ test decisions without leakage
→ validate on external real data
→ update incrementally and recover exactly
→ expose a bounded reporting product
→ evolve its consumer contract without silent migration
→ isolate concurrent consumers without changing the answer
```
