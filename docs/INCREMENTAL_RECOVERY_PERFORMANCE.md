# Incremental recovery and performance (v0.37)

v0.37 turns the v0.36 UCI Online Retail II evidence lane from a correct full-rebuild analysis into a recoverable incremental data product. The same pinned public source is retained: **1,067,371 real transaction rows**. No live-company or production-system claim is added.

## Problem found in v0.36

The v0.36 external lane was deliberately simple and reproducible, but every rebuild paid two avoidable repeat costs:

1. decompress and parse the full XLSX workbook into Python objects;
2. rescan the full 1,067,371-row transaction snapshot to rebuild daily metrics.

The first v0.37 performance run also exposed an implementation-level inefficiency in the initial incremental design: each monthly partition opened its own DuckDB connection and was scanned once for `COUNT(*)` and again for aggregation. The system was correct, but initial incremental materialisation took **0.591 s** in that diagnostic CI run, slower than a clean Parquet full aggregation.

The fix was structural rather than threshold-based:

- reuse one DuckDB connection across all changed partitions in a run;
- use the immutable canonical manifest's certified row count instead of a second `COUNT(*)` source scan;
- scan each changed partition once for aggregation;
- keep large-source SHA verification as an explicit integrity audit instead of charging it to every no-op run.

A subsequent GitHub Actions run observed initial incremental materialisation at **0.269 s**, about 54.5% lower than the earlier diagnostic run. These wall-clock values are diagnostics from shared CI runners, not a performance SLA or a stable public claim.

## Architecture

```text
pinned official UCI XLSX
        ↓ one-time source adaptation
canonical transaction frame
        ↓
25 immutable month-partitioned Parquet files
+ row counts / byte sizes / SHA-256 manifest
        ↓
durable per-partition materialisation state
        ↓
only missing / revised / invalidated partitions
        ↓
monthly daily-metric Parquet
        ↓
portfolio daily metric materialisation
        ↓
full-rebuild parity validation
```

The 25 canonical partitions contain exactly **1,067,371 rows** and occupy **9,806,373 bytes** in the reference run, versus the pinned **45,622,278-byte** workbook: about **78.5% less storage** after the one-time canonical conversion.

`InvoiceDate` is used to replay the historical source by calendar month. It is **event time, not ingestion time**. v0.37 therefore does not reinterpret these partitions as evidence about real arrival order, late events or watermark behaviour.

## Correctness before performance

Incremental processing is accepted only when it is exactly reconcilable to a clean rebuild. After the declared six-decimal normalisation for GBP revenue, all of the following must match exactly:

- date;
- revenue;
- orders;
- units;
- purchase-line count;
- active-customer count.

The reference run passes clean full-rebuild vs uninterrupted incremental parity over all 739 calendar days.

## Idempotent no-op

After the initial 25 partitions are complete, rerunning the same immutable source must produce:

```text
processed partitions        0
source rows SQL-scanned     0
large source SHA scans      0
output hash changes         0
```

Normal reuse still validates source file existence/size, source manifest identity, durable state and the compact materialised-output SHA. Full source SHA verification remains available as an explicit integrity audit and checks all 25 source partitions.

## Interrupted-run recovery

The reference deliberately interrupts a run after seven partitions have been durably committed.

```text
completed before interruption     7 partitions
rows already durable              257,045
restart partitions skipped        7
restart partitions processed      18
restart source rows scanned        810,326
full source rows                 1,067,371
```

The restart therefore reuses **257,045 already-validated rows** rather than replaying them. The recovered result is exactly equal to the uninterrupted build, including the final materialised partition hashes.

This is a recovery test, not merely a checkpoint count: state is persisted after every successful partition and the resumed output is reconciled to the clean full rebuild.

## Targeted repair

The reference corrupts the derived `2010-12` materialisation while leaving its canonical source partition unchanged. The output SHA mismatch invalidates only that month.

```text
affected source partition       2010-12
rows in affected partition       65,004
full source rows              1,067,371
rows scanned during repair       65,004
scan reduction vs full rebuild    93.91%
partitions rebuilt                    1
```

After repair, the materialised partition hashes are exactly restored and the full daily result again matches the clean rebuild.

A unit test separately changes a canonical source month and its manifest. Only that changed month is recomputed, demonstrating source-revision invalidation as distinct from derived-output corruption.

## Performance evidence

Performance is reported in two layers.

### Deterministic work contract

These are stable CI-gated facts:

| Operation | Source rows scanned | Reduction vs full 1,067,371-row scan |
|---|---:|---:|
| Clean rebuild baseline | 1,067,371 | 0% |
| Idempotent no-op | **0** | **100%** |
| Targeted `2010-12` repair | **65,004** | **93.91%** |
| Restart after seven durable partitions | **810,326** | **24.08%** |

These claims are checked against `results/incremental_reference_summary.csv`. The static validator deliberately rejects wall-clock timing or speed-up fields in that ledger.

### Diagnostic GitHub Actions timings

One post-optimisation run observed:

| Stage | Observed time |
|---|---:|
| XLSX parse + canonical normalisation | **54.99 s** |
| One-time canonical Parquet write | 3.80 s |
| Legacy Pandas full daily metric build | 0.518 s |
| Clean DuckDB full Parquet rebuild | **0.0996 s** |
| Initial partitioned incremental materialisation | 0.269 s |
| Idempotent no-op replay | **0.00166 s** |
| Targeted one-month repair | 0.0257 s |
| Full source SHA integrity audit | 0.0110 s |

The main bottleneck is therefore **source-format conversion**, not metric aggregation. Once the XLSX is converted to canonical Parquet, a full DuckDB metric rebuild itself is already very fast. Incremental processing is valuable for repeated no-op/revision/recovery work and for making the operational contract explicit; it is not presented as a claim that partitioning always beats one vectorised full scan on a 1M-row local dataset.

That distinction matters. On this dataset a clean Parquet full aggregation can be faster than the first 25-partition materialisation because partition orchestration/state persistence has overhead. v0.37 optimises that overhead while retaining the more important property: unchanged and targeted-repair runs avoid irrelevant source work.

## Evidence and validators

`build_incremental_retail_reference.py` generates:

```text
incremental_source_partition_manifest.csv
incremental_materialisation_manifest.csv
incremental_full_rebuild_daily.csv
incremental_daily_metrics.csv
incremental_contract.json
incremental_recovery_evidence.json
incremental_performance.json
incremental_summary.json
```

`validate_incremental_retail_reference.py` independently:

- SHA-verifies all 25 canonical source partitions;
- rebuilds daily metrics directly from source Parquet in DuckDB;
- verifies exact full/incremental parity;
- verifies output partition hashes against durable state;
- checks no-op, restart and targeted-repair work accounting.

`validate_incremental_static_claims.py` binds the deterministic public claims to the generated evidence and intentionally forbids stable timing/speed-up claims.

## Limits

- UCI Online Retail II is historical public transaction data, not a live event stream.
- `InvoiceDate` is not an ingestion timestamp; no real-data late-arrival or watermark claim is made.
- The benchmark is single-node DuckDB on GitHub-hosted runners; it does not measure object-store latency, cluster scheduling or distributed shuffle costs.
- Shared-runner wall-clock observations are diagnostic only.
- Monthly partitioning is a transparent reference policy for this historical replay, not a universal production partition choice.
- The source XLSX still has a substantial one-time parse cost. In a real platform the preferred upstream contract would normally emit a columnar/stream-friendly format rather than repeatedly using Excel as an interchange layer.
