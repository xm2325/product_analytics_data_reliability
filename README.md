# Product Analytics & Data Reliability Workbench

**Version:** v0.39  
**Stack:** Python · DuckDB · SQL · Pandas · NumPy · SciPy · Statsmodels · Parquet · Pytest · GitHub Actions

A reproducible analytics workbench for deciding when data, metrics, forecasts and experiments are trustworthy enough to support a business decision — and for exposing validated metrics through a bounded consumer contract that can evolve without silently breaking existing consumers.

The repository has five complementary evidence layers:

```text
controlled synthetic evidence
    -> failure injection, point-in-time correctness, metric migration,
       forecasting, experiment guardrails and decision boundaries

public real-world evidence
    -> external schema adaptation, source quality, metric semantics,
       frozen forecast portability and independent recomputation

real-world operational evidence
    -> immutable partitions, incremental processing, idempotency,
       interruption recovery, targeted repair and performance diagnosis

consumer data-product evidence
    -> bounded historical queries, metric catalogue, zero-fill,
       provenance, integrity-before-serve and JSON/CSV outputs

consumer contract-evolution evidence
    -> explicit schema negotiation, field-level compatibility classification,
       golden real-data responses and breaking-change gates
```

The design principle is unchanged: **a technically successful calculation is not automatically a trustworthy, operationally efficient, safely consumable or backward-compatible decision input**.

## v0.39 headline: evolve the interface without silently migrating consumers

v0.39 separates the **data-product release version** from the **consumer response schema version**. The package advances to `0.39.0`, but existing JSON consumers still receive schema **1.0** unless they explicitly request schema **1.1**.

Schema 1.1 is deliberately small. It adds one top-level `contract` object containing the schema family, negotiated version, an explicit backward-compatibility path and a deterministic SHA-256 of the metric catalogue. It does not redefine the five metrics, reparse the source workbook or change partition selection.

| v0.39 contract-evolution check | Validated result |
|---|---:|
| Data-product version | **0.39.0** |
| Schema family | **`retail-daily-metrics`** |
| Default JSON schema | **1.0** |
| Latest opt-in JSON schema | **1.1** |
| Supported schemas | **2** |
| Schema 1.0 top-level fields | **9** |
| Schema 1.1 top-level fields | **10** |
| Additional 1.1 top-level field | **`contract` only** |
| Real compatibility query | **7 days** |
| 1.0 ↔ 1.1 query payload | **exact match** |
| 1.0 ↔ 1.1 metric rows | **exact match** |
| 1.0 ↔ 1.1 query/data response SHA-256 | **exact match** |
| 1.0 ↔ 1.1 deterministic work selection | **exact match** |
| Unsupported schema | **rejected** |
| Governed migration proposals | **3** |
| Additive migrations approved | **1** |
| Breaking migrations withheld | **2** |
| Contract/incremental/reporting focused tests | **15 passed** |
| Full repository tests | **99 passed** |

The compatibility evidence runs on the same validated **1,067,371-row UCI Online Retail II** source used by the real operational lane. The pinned query is `2010-12-01` through `2010-12-07`. Both schema versions return the same query, same metric rows, same stable query/data hash and the same selected-partition work; schema 1.1 changes only the negotiated envelope.

### No silent default migration

An unversioned call remains on schema 1.0:

```bash
python scripts/query_retail_metrics.py \
  --incremental-dir build/incremental-retail \
  --start 2010-12-01 \
  --end 2010-12-07 \
  --metrics revenue_gbp,orders,active_customers \
  --format json
```

Consumers opt in to the additive schema explicitly:

```bash
python scripts/query_retail_metrics.py \
  --incremental-dir build/incremental-retail \
  --start 2010-12-01 \
  --end 2010-12-07 \
  --metrics revenue_gbp,orders,active_customers \
  --format json \
  --schema-version 1.1
```

CSV remains the stable date/metric row projection; schema negotiation governs the JSON envelope.

### Breaking changes are non-compensatory

Three concrete proposals are classified field by field against published schema 1.0:

| Proposal | Classification | Decision | Reason |
|---|---|---|---|
| add `contract` metadata through explicit schema 1.1 | ADDITIVE | **APPROVE** | Existing consumers can remain on negotiated schema 1.0. |
| rename `row_count` → `rows` | BREAKING | **WITHHOLD** | A published top-level field disappears. |
| change `orders` from integer → float | BREAKING | **WITHHOLD** | A published metric type changes. |

The independent CI validator does not import the production classifier. It reconstructs the serialised schema field maps, recomputes all three diffs/actions, independently recomputes both query/data response hashes and independently recomputes the metric-catalogue SHA.

**Compatibility boundary:** `ADDITIVE` is not a claim that every possible JSON parser accepts unknown fields. A strict existing client can continue to request schema 1.0. No production deprecation schedule or support-lifetime SLA is claimed.

See [`docs/CONSUMER_CONTRACT_EVOLUTION.md`](docs/CONSUMER_CONTRACT_EVOLUTION.md).

## v0.38: a bounded reporting data product

v0.38 turned the validated v0.37 real-data metric store into a small consumer-facing data product rather than adding another model or dashboard. Python defines the stable contract, DuckDB reads only relevant metric partitions, and the CLI exposes JSON or CSV.

Five allowlisted daily metrics are available:

- `revenue_gbp`
- `orders`
- `units`
- `purchase_lines`
- `active_customers`

Every JSON response carries the schema/data-product versions, normalised query, historical availability, selected metric-partition provenance, row count, deterministic response SHA-256 and data rows. Missing calendar days are explicitly zero-filled.

| reporting check | Validated result |
|---|---:|
| Backing metric partitions | **25** |
| Historical availability | **2009-12-01 → 2011-12-09** |
| Maximum query span | **366 days** |
| Reference query | **7 days** |
| Metric-value partitions selected | **1 / 25** |
| Metric-partition selection reduction | **96%** |
| Response vs validated daily layer | **exact match** |
| Cross-month reference query | **exactly 2 partitions** |
| Unknown metric | **rejected** |
| Over-wide / invalid range | **rejected** |
| Deliberately corrupted selected partition | **rejected before serve** |

The **96%** figure is deliberately narrow: it is a reduction in metric-value partition selection for the seven-day reference query relative to reading all 25 monthly metric partitions. Store initialisation separately integrity-checks and reads the first/last boundary partitions. It is not a 96% end-to-end latency or source-row reduction claim.

The first v0.38 CI attempt exposed an integrity-ordering flaw: DuckDB tried to open a deliberately corrupted boundary Parquet before the reporting layer validated its SHA. The implementation was changed so canonical source binding, durable state and metric SHA all agree **before DuckDB may read the file**. A second real-data tamper case on middle partition `2010-12` confirms query-time rejection too.

The reporting layer reuses validated metric partitions. It does **not** reparse the 45 MB XLSX or rescan the 1,067,371-row canonical source merely to answer a consumer query.

See [`docs/REPORTING_DATA_PRODUCT.md`](docs/REPORTING_DATA_PRODUCT.md).

## v0.37: incremental processing, recovery and performance

v0.37 keeps the pinned UCI Online Retail II source used in v0.36 — **1,067,371 real historical transaction rows** — but stops treating every run as a full rebuild. The source is canonicalised once into **25 immutable monthly Parquet partitions** with row counts, byte sizes and SHA-256 provenance. Durable state is committed after each successful metric partition.

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

| operational check | Validated result |
|---|---:|
| Real source rows | **1,067,371** |
| Canonical month partitions | **25** |
| Canonical Parquet bytes | **9,806,373** |
| Source workbook bytes | 45,622,278 |
| Full vs incremental daily metrics | **exact match** |
| Idempotent no-op source rows scanned | **0** |
| Large source partitions re-hashed in normal no-op | **0** |
| Durable rows reused after simulated restart | **257,045** |
| Restart partitions skipped | **7** |
| Targeted repair partition | `2010-12` |
| Targeted repair source rows scanned | **65,004** |
| Repair scan reduction vs full source | **93.91%** |
| Repaired output hashes restored | **exact match** |
| Explicit full source integrity audit | **25 / 25 SHA-verified** |

The main first-load bottleneck is XLSX decompression/XML parsing and canonical type normalisation, not the analytical DuckDB aggregation. Shared-runner timings are therefore diagnostic only. The stable performance contract is deterministic work avoided: a no-op scans **0 rows**, targeted `2010-12` repair scans **65,004 rows**, and restart after seven durable partitions scans **810,326 rows** instead of 1,067,371.

See [`docs/INCREMENTAL_RECOVERY_PERFORMANCE.md`](docs/INCREMENTAL_RECOVERY_PERFORMANCE.md).

## v0.36: real-world portability

The external lane uses **UCI Online Retail II**, real historical transactions from a UK-based non-store online retailer covering 1 December 2009 to 9 December 2011 (DOI `10.24432/C5CG6D`, CC BY 4.0). The raw workbook is not committed. GitHub Actions downloads the official source, verifies pinned archive/workbook SHA-256 values, adapts both workbook sheets and independently rebuilds the evidence.

| real-data check | Validated result |
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

Frozen forecast rules are not retuned after seeing the external data. `orders`, for example, has **15.31% WAPE** and substantially beats the last-value benchmark, but **20.94% MAPE** exceeds the pre-existing 20% limit, so it remains **WITHHOLD**.

Two plausible semantic replacements are also withheld as silent drop-ins: signed transaction value shifts purchase revenue by **-8.04%**, and any-transaction customer population shifts the purchasing-customer population by **+1.09%** against the declared 1% compatibility tolerance.

See [`docs/REAL_DATA_PORTABILITY.md`](docs/REAL_DATA_PORTABILITY.md).

## Controlled evidence: reproduce hard decision boundaries

Synthetic evidence is retained where the public real source lacks the fields needed for a controlled counterexample.

### Metric/producer contract evolution

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

Three independent CI lanes protect different evidence boundaries. The operational lane now also validates reporting and consumer-contract evolution.

```text
controlled synthetic lane
  pytest (99 repository tests)
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

incremental operational + reporting + contract lane
  official pinned UCI download
  → canonical 25-partition Parquet snapshot
  → interruption / no-op / repair scenarios
  → independent full-rebuild parity + source/output SHA audit
  → bounded five-metric reporting interface
  → partition pruning + tamper rejection + response reconciliation
  → schema 1.0 default + explicit schema 1.1 negotiation
  → independently recomputed compatibility classifications
  → JSON 1.0 / JSON 1.1 / CSV consumer smoke tests
```

## Reproduce

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -e .

make check             # controlled deterministic lane
make real-check        # network-enabled UCI portability lane
make incremental-check # network-enabled recovery/reporting/contract lane
```

## Claim boundaries

- UCI Online Retail II is public real-world historical transaction data; this repository is not a production deployment and does not claim access to a company's private systems.
- `InvoiceDate` is event time, **not ingestion time**. Real-data late-arrival, watermark, processing-time SLA and point-in-time/as-of reconstruction are therefore not claimed.
- The reporting layer is a local Python/CLI data-product boundary, not a deployed network service or production availability/latency claim.
- The **96%** reporting figure is metric-partition-selection reduction for the pinned seven-day query, not source-row reduction and not a latency speedup.
- Schema 1.1 being additive does not imply universal parser compatibility; strict existing consumers retain explicit schema 1.0 negotiation.
- No production consumer-support lifetime or deprecation schedule is claimed.
- The 1% metric semantic tolerance is a declared workbench governance threshold, not a universal industry threshold.
- Forecast thresholds were frozen before external evaluation; failed real-data gates are reported rather than tuned away.
- Shared GitHub-runner timings are diagnostic only. Public performance claims use deterministic rows/partitions selected or scanned and exact parity.
- Operational evidence is single-node DuckDB/Parquet; it does not claim distributed-system, object-store or production-network benchmarks.

The progression is:

```text
trust the source
→ define the metric explicitly
→ preserve point-in-time semantics where the source supports them
→ test decisions without leakage
→ validate on external real data
→ update incrementally without losing reproducibility
→ recover and repair without silently changing the answer
→ expose validated metrics through a bounded consumer contract
→ evolve that contract without silently migrating existing consumers
```
