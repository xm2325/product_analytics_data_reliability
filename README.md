# Product Analytics & Data Reliability Workbench

**Version:** v0.41  
**Stack:** Python · DuckDB · SQL · Pandas · NumPy · SciPy · Statsmodels · Parquet · Pytest · GitHub Actions

A reproducible analytics workbench for deciding when data, metrics, forecasts and experiments are trustworthy enough to support a business decision — and for keeping those decisions trustworthy when upstream data, metric definitions, consumer contracts and concurrent workloads evolve.

The repository now has seven complementary evidence layers:

```text
controlled synthetic evidence
    -> failure injection, point-in-time correctness, metric migration,
       forecasting, experiment guardrails and decision boundaries

selective evidence invalidation
    -> governed dependency fingerprints, lineage-aware stale propagation,
       fail-closed downstream actions and false-positive avoidance

public real-world evidence
    -> external schema adaptation, source quality, metric semantics,
       frozen forecast portability and independent recomputation

real-world operational evidence
    -> immutable partitions, incremental processing, idempotency,
       interruption recovery, targeted repair and deterministic work diagnosis

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

The design principle is: **a result is not trustworthy merely because it was correct when first computed. It must still be supported by the same governed evidence assumptions when someone acts on it.**

## v0.41 headline: upstream changes must invalidate only the evidence they actually break

v0.35 already classified additive, breaking and semantic migrations. It also showed a subtle case: broadening DAU from `app_open` to any certified event changed aggregate DAU by up to **+4.94%**, yet the three downstream DAU forecast eligibility states happened to remain unchanged.

That is not enough to keep the old forecasts trustworthy.

v0.41 adds an explicit **16-node evidence dependency DAG**. Each governed dependency surface receives a deterministic SHA-256 fingerprint. A stored result becomes stale when either:

1. its own governed fingerprint changes; or
2. any dependency it was built from is stale.

Stale evidence fails closed as `WITHHOLD_STALE`. The original business action is preserved separately, so evidence freshness cannot accidentally rewrite a `HOLD`, `WITHHOLD` or `APPROVE` conclusion.

### Scoped fingerprints, not one global contract hash

Hashing the entire event contract would create noisy false positives. For example, adding an unused optional `country` field changes the JSON document but should not invalidate forecasts that do not use that field.

v0.41 therefore fingerprints four governed root surfaces:

- producer shape: grain, required columns and processing-time obligations;
- DAU semantics: activity event and active-use rule;
- revenue semantics: value and revenue-scope rules;
- paid-subscription semantics: subscription-event surface.

The controlled scenarios reuse the existing v0.35 migration proposals:

| Change | Existing migration action | Fresh | Direct stale | Downstream stale | Total stale | Pricing chain fresh |
|---|---|---:|---:|---:|---:|---|
| add optional `country` | **APPROVE** | 16 | 0 | 0 | 0 | yes |
| broaden DAU to any certified event | **WITHHOLD** | 8 | 1 | 7 | 8 | yes |
| rename required `event_id` → `event_uuid` | **WITHHOLD** | 3 | 1 | 12 | 13 | no |

The most important case is the DAU semantic change:

```text
semantic:dau                 DIRECT_STALE
    ↓
metric:dau                   DOWNSTREAM_STALE
    ↓
3 DAU forecasts              DOWNSTREAM_STALE
    ↓
3 DAU planning decisions     DOWNSTREAM_STALE
```

The pricing experiment, impact scenario and rollout authorisation remain fresh because they depend on revenue and paid-subscription semantics, not DAU. Their baseline actions remain `HOLD`, `COUNTERFACTUAL_ONLY` and `WITHHOLD`.

So v0.41 demonstrates both sides of correct invalidation:

- **do invalidate** evidence whose semantic assumptions changed, even if its old numeric decision happened to stay the same;
- **do not invalidate** unrelated evidence merely because some global contract document changed.

The independent validator reconstructs the DAG, fingerprints and propagation logic without importing the production invalidation module.

See [`docs/EVIDENCE_INVALIDATION.md`](docs/EVIDENCE_INVALIDATION.md).

## v0.40: concurrent consumers must not change the answer

v0.40 keeps the v0.39 response schemas and metric semantics unchanged but strengthens the execution boundary. Immutable manifest/state metadata are shared; **every query creates and closes its own request-local DuckDB connection**.

The real reference workload runs on the pinned **1,067,371-row UCI Online Retail II** source and 25-partition metric store.

| v0.40 workload-isolation check | Validated result |
|---|---:|
| Reporting data-product version | **0.40.0** |
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

The deterministic workload fingerprint is:

```text
ef1adcc2dc091ad9ad00c16175ea7b38c8f6fec084c4c1700c6c50c127376e7e
```

The six repeated hot-window consumers read the same declared data, return one identical full-payload hash and do not share mutable query-engine state. Three deliberately invalid consumers — unknown metric, unsupported schema `2.0`, duplicate metric — fail through `ReportingContractError` without changing any healthy result in the same concurrent batch or in a later healthy replay.

v0.40 deliberately has **no QPS, latency, throughput or speedup gate**. Shared GitHub runners are unsuitable evidence for a stable capacity claim. The public claim is deterministic result isolation and work accounting on one process / one node, not a distributed-service SLA.

See [`docs/WORKLOAD_ISOLATION.md`](docs/WORKLOAD_ISOLATION.md).

## v0.39: evolve the interface without silently migrating consumers

The data-product release version is separated from the consumer response schema. Existing/unversioned JSON consumers remain on schema **1.0**; schema **1.1** is explicit opt-in and adds only a top-level `contract` metadata object.

The same seven-day real-data query under schemas 1.0 and 1.1 preserves query payload, metric rows, response SHA and deterministic partition work exactly.

| Proposal | Classification | Decision |
|---|---|---|
| add negotiated `contract` metadata | ADDITIVE | **APPROVE** |
| rename `row_count` → `rows` | BREAKING | **WITHHOLD** |
| change `orders` integer → float | BREAKING | **WITHHOLD** |

Additive does not imply universal parser compatibility; strict existing consumers can stay on schema 1.0.

See [`docs/CONSUMER_CONTRACT_EVOLUTION.md`](docs/CONSUMER_CONTRACT_EVOLUTION.md).

## v0.38: bounded reporting data product

Five allowlisted daily metrics are exposed through a framework-independent Python interface and JSON/CSV CLI:

- `revenue_gbp`
- `orders`
- `units`
- `purchase_lines`
- `active_customers`

The reporting store covers **2009-12-01 through 2011-12-09**, limits a request to **366 days**, zero-fills missing calendar days and SHA-verifies selected metric partitions before serving them.

The pinned seven-day query selects **1 of 25** monthly metric partitions for metric values — a **96% partition-selection reduction**, not a latency claim — and exactly reconciles to the validated daily layer. Unknown, over-wide and tampered requests fail closed.

See [`docs/REPORTING_DATA_PRODUCT.md`](docs/REPORTING_DATA_PRODUCT.md).

## v0.37: incremental recovery and targeted repair

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

Shared-runner timings remain diagnostic; public performance evidence uses deterministic rows, partitions, hashes and exact parity.

See [`docs/INCREMENTAL_RECOVERY_PERFORMANCE.md`](docs/INCREMENTAL_RECOVERY_PERFORMANCE.md).

## v0.36: external real-world portability

The external lane uses **UCI Online Retail II**, public real historical transactions from a UK-based non-store online retailer (DOI `10.24432/C5CG6D`, CC BY 4.0). GitHub Actions downloads the official source and verifies pinned archive/workbook SHA-256 values.

Observed source facts include **1,067,371 rows**, **739 calendar days**, **1,041,670 valid purchase-line rows**, **243,007 missing CustomerID rows**, **19,494 cancellation rows** and **12,133 exact duplicates** excluding the generated source-row ID.

Real data is allowed to fail frozen rules. All four external forecast series are withheld under the pre-existing forecasting contract. `orders`, for example, has **15.31% WAPE** but **20.94% MAPE**, just above the frozen 20% gate. Two plausible metric replacements are also withheld as silent drop-ins because signed transaction value changes purchase revenue by **-8.04%** and the any-transaction customer population changes the purchasing-customer population by **+1.09%** against the declared 1% compatibility tolerance.

See [`docs/REAL_DATA_PORTABILITY.md`](docs/REAL_DATA_PORTABILITY.md).

## Controlled decision evidence

Synthetic evidence is retained where the public source lacks the fields needed for controlled counterexamples.

### Metric and producer evolution — v0.35

A **450 product-day shadow replay** evaluates three migration proposals. Optional `country` is approved; required `event_id → event_uuid` and DAU semantic broadening are withheld. The semantic candidate changes aggregate DAU by up to **+4.94%** even though downstream forecast eligibility happens not to change.

### Forecast decisioning — v0.34

The controlled forecast reference evaluates four rolling origins × seven-day horizons. `photo_editor:dau` has only **3.92% WAPE**, but the simpler last-value benchmark has **2.56%**, so the candidate remains withheld. Low absolute error is not sufficient if a trivial benchmark is better.

### Experiment and impact decisioning — v0.32–v0.33

The deterministic 8,000-user pricing experiment estimates **+£0.6851/user/30d** with a positive 95% confidence interval, but its paid-conversion guardrail fails. The experiment remains **HOLD**.

The hypothetical cohort plan treats **150,000** users and implies about **£102,762** counterfactual 30-day incremental revenue, but because the experiment is still HOLD, decision-authorised treated users remain **0** and authorised incremental revenue remains null.

### Freshness uncertainty

Controlled processing-time evidence distinguishes observed stability from statistical certification. A 96h candidate is stable across nine rolling windows, but **no candidate is certified at 95% family-wise confidence** under the declared model.

The real UCI source has invoice/event time but no independent ingestion timestamp, so the repository does not fabricate a real-data watermark/as-of claim.

## Validation architecture

The repository keeps historical evidence boundaries explicit rather than rewriting old bundles when a later release adds a new concern.

```text
controlled deterministic lane
  full pytest suite
  → frozen v0.35 reference build
  → forecast / migration validators
  → v0.41 dependency-graph build
  → independent v0.41 stale-propagation validator
  → watermark / uncertainty / evidence-plan validators
  → experiment / impact validators
  → frozen v0.35 pinned/static claim validators

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

make check             # controlled reference + v0.41 invalidation validation
make real-check        # network-enabled external UCI lane
make incremental-check # network-enabled recovery/reporting/contract/workload lane
```

The v0.41 evidence layer can also be run directly after building the controlled reference:

```bash
make reference
make invalidation-reference
make invalidation-validate
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
- v0.41 is controlled dependency-invalidation evidence over a declared 16-node graph; it is not a production lineage catalogue, scheduler or distributed invalidation system.
- v0.41 deliberately separates package/repository version **0.41.0** from the unchanged reporting data-product version **0.40.0** and unchanged response schemas **1.0 / 1.1**.
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
→ govern schema and metric changes
→ invalidate stale downstream evidence selectively
→ validate on external real data
→ update incrementally and recover exactly
→ expose a bounded reporting product
→ evolve its consumer contract without silent migration
→ isolate concurrent consumers without changing the answer
```
