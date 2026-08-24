# Product Analytics & Data Reliability Workbench

**Version:** v0.37  
**Stack:** Python · DuckDB · SQL · Pandas · NumPy · SciPy · Statsmodels · Parquet · Pytest · GitHub Actions

A reproducible analytics workbench for deciding when data, metrics, forecasts and experiments are trustworthy enough to support a business decision — and whether the underlying data product can be replayed, recovered and updated without unnecessary full recomputation.

The repository now has three complementary evidence layers:

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
```

The design principle is unchanged: **a technically successful calculation is not automatically a trustworthy or operationally efficient decision input**.

## v0.37 headline: incremental processing, recovery and performance

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
| Full repository tests | **88 passed** |

The checked-in v0.37 claim ledger pins the deterministic work counts above. It deliberately does **not** pin shared-runner wall-clock timings.

### Why performance was slow

The first performance investigation separated two different problems.

**1. Source-format bottleneck.** The official source is XLSX. In a post-optimisation CI run, decompressing/parsing the workbook and normalising 1.07M rows took about **54.99 s**. Once converted to canonical Parquet, a clean DuckDB aggregation over the full source took only about **0.100 s**. The dominant first-load cost is therefore Excel/XML parsing, not metric aggregation.

**2. Initial incremental implementation overhead.** The first v0.37 implementation opened a DuckDB connection per monthly partition and scanned each changed partition twice: once for `COUNT(*)`, then again for aggregation. It was correct, but the observed initial incremental materialisation took **0.591 s**.

The implementation was changed to:

```text
one DuckDB connection per run
+ manifest-certified row counts
+ one source scan per changed partition
```

A subsequent CI run observed **0.269 s**, about **54.5% lower** than the earlier diagnostic run. These timings come from different shared GitHub runners and are therefore diagnostic, not an SLA or a universal 2× speed claim.

### What is actually performance-gated

Deterministic work reduction is the contract:

| Operation | Source rows scanned | Reduction vs 1,067,371-row full scan |
|---|---:|---:|
| Full rebuild baseline | 1,067,371 | 0% |
| Idempotent no-op | **0** | **100%** |
| Targeted `2010-12` repair | **65,004** | **93.91%** |
| Restart after seven durable partitions | **810,326** | **24.08%** |

This avoids a misleading claim that partitioning must always beat a single vectorised full scan. On this local 1M-row Parquet dataset, a clean full DuckDB aggregation is already extremely fast; the incremental design is valuable because unchanged/repaired/restarted runs do not repeat irrelevant source work and because the state is recoverable and auditable.

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
| positive non-cancelled purchase revenue -> signed transaction ledger | **-8.04%** | **WITHHOLD** |
| purchasing-customer population -> any-transaction customer population | **+1.09%** | **WITHHOLD** |

The alternative metrics may be useful under new names; the result only says they are not backward-compatible replacements within the declared 1% semantic tolerance.

See [`docs/REAL_DATA_PORTABILITY.md`](docs/REAL_DATA_PORTABILITY.md).

## Controlled evidence: reproduce hard decision boundaries

Synthetic data remain useful where the public real source lacks the required fields or where a controlled counterexample is the point of the test.

### Contract evolution

v0.35 separates producer compatibility, metric semantic safety and downstream decision stability.

| Proposal | Class | Producer compatible | Metric invariant | Forecast stable | Action |
|---|---|---:|---:|---:|---|
| add optional `country` | ADDITIVE | PASS | PASS | PASS | **APPROVE** |
| broaden DAU to any certified event | SEMANTIC | PASS | **FAIL** | PASS | **WITHHOLD** |
| rename required `event_id` -> `event_uuid` | BREAKING | **FAIL** | PASS | PASS | **WITHHOLD** |

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

Three independent CI lanes protect different evidence boundaries.

```text
controlled synthetic lane
  pytest (88 repository tests)
  -> deterministic reference build
  -> forecast / migration / watermark / uncertainty validators
  -> experiment / impact validators
  -> pinned and static claim validators

real-data portability lane
  official pinned UCI download
  -> source adapter / quality / metrics
  -> semantic and frozen forecast evidence
  -> independent DuckDB/Python recomputation
  -> checked-in real-data claim ledger

incremental operational lane
  official pinned UCI download
  -> canonical 25-partition Parquet snapshot
  -> interruption / no-op / repair scenarios
  -> independent full rebuild parity
  -> source/output SHA audit
  -> checked-in deterministic work ledger
```

## Reproduce

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -e .

make check             # controlled deterministic lane
make real-check        # network-enabled UCI portability lane
make incremental-check # network-enabled v0.37 recovery/performance lane
```

## Claim boundaries

- UCI Online Retail II is public real-world historical transaction data; this repository is not a production deployment and does not claim access to a company's private systems.
- `InvoiceDate` is event time, **not ingestion time**. Monthly v0.37 partitions represent historical replay, not real arrival order.
- Real-data late-arrival, watermark or processing-time SLA behaviour is therefore not claimed; those remain controlled synthetic evidence.
- The 1% semantic tolerance is a declared workbench governance threshold, not a universal industry threshold.
- Forecast thresholds were frozen before the external evaluation; failed real-data gates are reported rather than tuned away.
- Shared GitHub-runner timings are diagnostic only. Public performance claims are based on deterministic rows/partitions scanned and exact parity.
- v0.37 is single-node DuckDB/Parquet evidence; it does not claim distributed-system, object-store or production-network benchmarks.

The progression is:

```text
trust the source
-> define the metric explicitly
-> preserve point-in-time semantics
-> test decisions without leakage
-> validate on external real data
-> update incrementally without losing reproducibility
-> recover and repair without silently changing the answer
```
