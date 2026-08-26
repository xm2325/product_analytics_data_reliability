# Product Analytics & Data Reliability Workbench

**Version:** v0.42  
**Stack:** Python · DuckDB · SQL · Pandas · NumPy · SciPy · Statsmodels · Parquet · Pytest · GitHub Actions

A reproducible analytics workbench for deciding when data, metrics, forecasts and experiments are trustworthy enough to support a business decision — and for keeping those decisions trustworthy as upstream data, KPI definitions, consumer contracts and concurrent workloads evolve.

The repository is organised around one principle:

> **A result is not trustworthy merely because it was correct when first computed. It must still be supported by the governed evidence assumptions in force when someone acts on it.**

The evidence chain now covers eight complementary layers:

```text
controlled decision evidence
    -> data quality, point-in-time correctness, metrics, forecasting,
       experiment guardrails, impact and decision boundaries

metric / producer change governance
    -> additive, semantic and breaking migration classification
       plus shadow replay and frozen compatibility thresholds

selective evidence invalidation
    -> dependency fingerprints, lineage-aware stale propagation,
       fail-closed downstream actions and false-positive avoidance

selective evidence revalidation
    -> explicit adoption, minimal rebuild sets, exact unaffected reuse,
       independent recovery verification and fail-closed blocked states

public real-world evidence
    -> UCI schema adaptation, source quality, metric semantics,
       frozen forecast portability and independent recomputation

real-world operational evidence
    -> immutable partitions, incremental processing, idempotency,
       interruption recovery, targeted repair and deterministic work accounting

consumer data-product / contract evidence
    -> bounded historical queries, provenance, integrity-before-serve,
       schema negotiation and breaking-change gates

multi-consumer execution evidence
    -> request-local query engines, serial/concurrent exact parity,
       deterministic work accounting and failure isolation
```

## v0.42 headline: stale evidence must be selectively rebuilt before reuse

v0.41 answered **which old evidence becomes stale when a governed dependency changes**. v0.42 answers the operational follow-up:

> **Can that evidence be recovered, and if so, what is the smallest governed rebuild that restores a fully fresh decision graph?**

The reference graph contains **16 evidence nodes**. A DAU semantic change makes exactly eight nodes stale:

```text
semantic:dau
    ↓
metric:dau
    ↓
3 DAU forecasts
    ↓
3 DAU planning decisions
```

The other eight nodes — producer shape, revenue/paid semantic and metric evidence, pricing experiment, impact and rollout authorisation — are unaffected.

### Silent replacement is still WITHHOLD

The frozen v0.35 migration proposal broadens DAU from `app_open` to any certified event. It changed portfolio DAU by up to **+4.94%**, above the pre-specified **1% semantic compatibility tolerance**, so it remains **WITHHOLD as a silent replacement**.

v0.42 does **not** relax that tolerance and does **not** reinterpret the historical decision.

Instead, it models a separate governance event: an explicit, versioned decision to adopt the new DAU definition. Only after that explicit adoption is the stale DAU evidence eligible for rebuilding.

```text
semantic candidate
      ↓
silent replacement?
      ├─ yes → original WITHHOLD remains binding
      └─ no, explicit versioned adoption
                  ↓
            selective revalidation
```

### Four governed recovery scenarios

| Scenario | Initial stale | Revalidated | Exact reused | Final stale | Result |
|---|---:|---:|---:|---:|---|
| optional `country` | 0 | 0 | 16 | 0 | **NOOP** |
| DAU silent replacement | 8 | 0 | 8 | 8 | **BLOCKED** |
| explicit versioned DAU adoption | 8 | 8 | 8 | 0 | **REVALIDATED** |
| required `event_id → event_uuid` producer break | 13 | 0 | 3 | 13 | **BLOCKED** |

The explicit DAU adoption therefore proves both **minimal recomputation** and **exact reuse**:

| Deterministic v0.42 work | Result |
|---|---:|
| Gold product-day metric rows recomputed | **450** |
| DAU forecast series recomputed | **3** |
| Planning decisions recomputed | **3** |
| Pricing-chain nodes recomputed | **0** |
| DAG nodes revalidated | **8** |
| DAG nodes reused exactly | **8** |
| Final fresh nodes | **16 / 16** |
| Final stale nodes | **0** |

The planner rejects partial rebuilds. A `READY` plan can only become `REVALIDATED` when replacement evidence exists for **every** planned stale node and the resulting graph independently verifies as fully fresh.

### The forecast evidence is genuinely rerun

The builder does not repair freshness by swapping hashes. It takes the frozen controlled Gold layer, adopts `dau_legacy_any_event` as the explicitly versioned candidate series, and reruns the existing leakage-safe rolling-origin forecast contract for all three products.

| Product | Candidate WAPE | Last-value benchmark WAPE | Interval coverage | Revalidated action |
|---|---:|---:|---:|---|
| `file_transfer` | **5.53%** | 7.58% | 100% | **APPROVE** |
| `notes_app` | **4.06%** | 4.51% | 100% | **APPROVE** |
| `photo_editor` | **3.77%** | 2.46% | 100% | **WITHHOLD** |

`photo_editor` remains deliberately instructive: the candidate has low absolute error, but the trivial last-value benchmark is better, so the planning action stays withheld after the semantic adoption.

The independent v0.42 validator reconstructs these candidate forecasts from Gold/Silver and cross-checks them against the separately validated frozen v0.35 migration replay. It also proves that all eight unaffected nodes are byte-for-byte equivalent at the model level and that the pricing experiment/impact/authorisation chain was not recomputed.

See [`docs/EVIDENCE_REVALIDATION.md`](docs/EVIDENCE_REVALIDATION.md).

## v0.41: upstream changes invalidate only the evidence they actually break

v0.41 introduced a **16-node evidence dependency DAG** with deterministic SHA-256 fingerprints over governed dependency surfaces rather than one noisy global contract hash.

A stored result becomes stale when either its own governed fingerprint changes or any dependency it was built from is stale. Stale evidence fails closed as `WITHHOLD_STALE`; the original business action remains separately recorded.

| Change | Existing migration action | Fresh | Direct stale | Downstream stale | Total stale | Pricing chain fresh |
|---|---|---:|---:|---:|---:|---|
| add optional `country` | **APPROVE** | 16 | 0 | 0 | 0 | yes |
| broaden DAU to any certified event | **WITHHOLD** | 8 | 1 | 7 | 8 | yes |
| rename required `event_id → event_uuid` | **WITHHOLD** | 3 | 1 | 12 | 13 | no |

The DAU case is the key counterexample: v0.35 found **0/3 forecast eligibility changes**, yet v0.41 correctly marks the old DAU forecast evidence stale because its KPI semantics changed. Unchanged downstream output cannot make stale evidence fresh.

The pricing experiment, impact and authorisation remain fresh under the DAU-only change because they depend on revenue and paid-subscription evidence, not DAU.

See [`docs/EVIDENCE_INVALIDATION.md`](docs/EVIDENCE_INVALIDATION.md).

## v0.40: concurrent consumers must not change the answer

The reporting store keeps immutable manifest/state metadata shared while every query creates and closes its own request-local DuckDB connection.

The reference workload uses the pinned **1,067,371-row UCI Online Retail II** source and its 25-partition metric store.

| Workload-isolation check | Validated result |
|---|---:|
| Reporting data-product version | **0.40.0** |
| Default / latest JSON schema | **1.0 / 1.1** |
| Valid requests / consumers | **12 / 12** |
| Concurrent workers | **8** |
| Mixed workload requests | **15** |
| Injected invalid consumers | **3** |
| Intended failures isolated | **3 / 3** |
| Aggregate metric partitions selected | **27** |
| Unique metric partitions touched | **16** |
| Aggregate response rows | **652** |
| Serial vs concurrent compact results | **exact parity** |
| Serial vs concurrent workload digest | **exact parity** |
| Parallel consumers on the same hot window | **6** |
| Unique full-payload hashes | **1** |

The deterministic workload fingerprint is:

```text
ef1adcc2dc091ad9ad00c16175ea7b38c8f6fec084c4c1700c6c50c127376e7e
```

Three deliberately invalid consumers — unknown metric, unsupported schema `2.0`, duplicate metric — fail without changing healthy results in the same concurrent batch or in a later healthy replay.

No QPS, latency, throughput or speedup gate is claimed from shared GitHub runners.

See [`docs/WORKLOAD_ISOLATION.md`](docs/WORKLOAD_ISOLATION.md).

## v0.39: evolve the interface without silently migrating consumers

The data-product release version is separate from the public response-schema version. Existing/unversioned JSON consumers remain on schema **1.0**; schema **1.1** is explicit opt-in.

| Proposal | Classification | Decision |
|---|---|---|
| add negotiated `contract` metadata | ADDITIVE | **APPROVE** |
| rename `row_count → rows` | BREAKING | **WITHHOLD** |
| change `orders` integer → float | BREAKING | **WITHHOLD** |

The same real-data request under schemas 1.0 and 1.1 preserves query payload, metric rows, response SHA and deterministic partition work exactly.

See [`docs/CONSUMER_CONTRACT_EVOLUTION.md`](docs/CONSUMER_CONTRACT_EVOLUTION.md).

## v0.38: bounded reporting data product

Five allowlisted daily metrics are exposed through a framework-independent Python interface and JSON/CSV CLI:

- `revenue_gbp`
- `orders`
- `units`
- `purchase_lines`
- `active_customers`

The reporting store covers **2009-12-01 through 2011-12-09**, bounds requests to **366 days**, zero-fills missing calendar days and SHA-verifies selected metric partitions before serving them.

The pinned seven-day query selects **1 of 25** monthly metric partitions for metric values — a **96% partition-selection reduction**, not a latency claim — and exactly reconciles to the validated daily layer. Unknown, over-wide and tampered requests fail closed.

See [`docs/REPORTING_DATA_PRODUCT.md`](docs/REPORTING_DATA_PRODUCT.md).

## v0.37: incremental recovery and targeted repair

The real source is canonicalised into **25 immutable monthly Parquet partitions** with row counts and SHA-256 provenance. Durable state supports exact restart, no-op and targeted repair behaviour.

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

Shared-runner timings remain diagnostic; stable claims use deterministic rows, partitions and hashes.

See [`docs/INCREMENTAL_RECOVERY_PERFORMANCE.md`](docs/INCREMENTAL_RECOVERY_PERFORMANCE.md).

## v0.36: external real-world portability

The external lane uses **UCI Online Retail II**, public real historical transactions from a UK-based non-store online retailer (DOI `10.24432/C5CG6D`, CC BY 4.0). GitHub Actions downloads the official source and verifies pinned archive/workbook SHA-256 values.

Observed source facts include **1,067,371 rows**, **739 calendar days**, **1,041,670 valid purchase-line rows**, **243,007 missing CustomerID rows**, **19,494 cancellation rows** and **12,133 exact duplicates** excluding the generated source-row ID.

Real data is allowed to fail frozen rules. All four external forecast series are withheld under the pre-existing forecasting contract. `orders`, for example, has **15.31% WAPE** but **20.94% MAPE**, just above the frozen 20% gate.

Two plausible metric replacements are also withheld as silent drop-ins because signed transaction value changes purchase revenue by **-8.04%** and an any-transaction customer population changes the purchasing-customer population by **+1.09%** against the declared 1% compatibility tolerance.

See [`docs/REAL_DATA_PORTABILITY.md`](docs/REAL_DATA_PORTABILITY.md).

## Controlled decision evidence

Synthetic evidence is retained where the public source lacks the fields needed for controlled counterexamples.

### Metric and producer evolution — v0.35

A **450 product-day shadow replay** evaluates three migrations. Optional `country` is approved; required `event_id → event_uuid` and DAU semantic broadening are withheld. The semantic candidate changes aggregate DAU by up to **+4.94%** even though downstream forecast eligibility happens not to change.

### Forecast decisioning — v0.34

The controlled forecast reference evaluates four rolling origins × seven-day horizons. `photo_editor:dau` has **3.92% WAPE**, but the simpler last-value benchmark has **2.56%**, so the candidate remains withheld. Low absolute error is not sufficient if a trivial benchmark is better.

### Experiment and impact decisioning — v0.32–v0.33

The deterministic 8,000-user pricing experiment estimates **+£0.6851/user/30d** with a positive 95% confidence interval, but its paid-conversion guardrail fails. The experiment remains **HOLD**.

A hypothetical 150,000-user cohort plan implies about **£102,762** counterfactual 30-day incremental revenue, but decision-authorised treated users remain **0** and authorised incremental revenue remains null.

### Freshness uncertainty

Controlled processing-time evidence distinguishes observed stability from statistical certification. A 96h candidate is stable across nine rolling windows, but **no candidate is certified at 95% family-wise confidence** under the declared model.

The real UCI source has invoice/event time but no independent ingestion timestamp, so no real-data watermark/as-of claim is fabricated.

## Validation architecture

Historical evidence boundaries are kept explicit instead of rewriting older bundles when a later release adds a new concern.

```text
controlled deterministic lane
  pytest (111 repository tests)
  → frozen v0.35 reference build
  → forecast / migration validators
  → v0.41 dependency-graph build + independent invalidation validator
  → v0.42 selective rebuild + independent revalidation validator
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

make check             # controlled reference + invalidation + revalidation
make real-check        # network-enabled external UCI lane
make incremental-check # recovery/reporting/contract/workload lane
```

The v0.41/v0.42 governance layers can be run directly after the controlled reference:

```bash
make reference
make invalidation-reference
make invalidation-validate
make revalidation-reference
make revalidation-validate
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
- v0.42 is controlled selective-revalidation evidence over a declared 16-node graph; it is not a production lineage scheduler, workflow engine or distributed build system.
- The v0.35 DAU semantic proposal remains WITHHOLD as a silent replacement. Explicit versioned adoption is a separate governance event, not a post-hoc relaxation of the 1% compatibility tolerance.
- Repository/package version **0.42.0** does not rewrite the frozen v0.35 controlled bundle, reporting data-product version **0.40.0**, or response schemas **1.0 / 1.1**.
- The reporting layer is a local Python/CLI data-product boundary, not a deployed network service.
- v0.40 proves request-local query execution and deterministic concurrent replay on one process / one node; it does not prove production QPS, tail latency, distributed isolation, fairness or capacity.
- The 96% reporting figure is metric-partition-selection reduction for one pinned query, not source-row reduction or latency speedup.
- Forecast thresholds were frozen before external evaluation; failed gates are reported rather than retuned away.
- Shared GitHub-runner timings are diagnostic only. Public operational claims use deterministic rows/partitions/hashes and exact parity.

The progression is:

```text
trust the source
→ define metrics explicitly
→ test decisions without leakage
→ govern schema and metric changes
→ invalidate stale downstream evidence selectively
→ explicitly adopt new semantics when intended
→ selectively rebuild only affected evidence
→ independently require the graph to become fully fresh
→ validate on external real data
→ update incrementally and recover exactly
→ expose a bounded reporting product
→ evolve its consumer contract without silent migration
→ isolate concurrent consumers without changing the answer
```
