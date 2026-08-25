# Multi-consumer workload isolation

v0.40 adds a deliberately narrow concurrency property to the reporting data product: multiple consumers may query the same immutable metric store without sharing mutable DuckDB query-execution state.

This is **not** a network-service load test and it is **not** a production throughput claim. The stable evidence is deterministic result isolation and work accounting on the pinned real UCI Online Retail II store.

## Why the execution boundary changed

The v0.39 `RetailMetricStore` retained one DuckDB connection and reused it across queries. That was sufficient for the single-consumer reference interface, but it was not a clean multi-consumer isolation boundary. Adding a lock around one shared connection would serialise access while preserving the same shared mutable query engine.

v0.40 instead separates shared immutable metadata from request-local execution:

```text
canonical source manifest + durable incremental state + metric files
                      ↓
          shared read-only store metadata
                      ↓
        ┌─────────────┼─────────────┐
        ↓             ↓             ↓
   request A      request B      request C
   DuckDB conn    DuckDB conn    DuckDB conn
        ↓             ↓             ↓
   close after     close after     close after
   request         request         request
```

Store construction still verifies boundary-partition integrity and historical availability. Every consumer query then creates and closes its own ephemeral DuckDB connection. The response schema, metric definitions, partition-integrity checks and schema negotiation remain unchanged: schema 1.0 is still the default and schema 1.1 remains explicit opt-in.

## Real reference workload

The network-enabled operational workflow first rebuilds the existing **1,067,371-row UCI Online Retail II** incremental store and all prior recovery/reporting/contract evidence. It then runs a deterministic workload over that same 25-partition metric store.

The valid workload contains **12 requests from 12 consumer identities**. It deliberately mixes:

- short and long date ranges;
- one-month, cross-month and year-scale queries;
- different metric projections;
- schema 1.0 and negotiated schema 1.1;
- six consumers requesting the same hot December 2010 window.

A serial baseline is compared with an **8-worker** concurrent replay. The contract is exact equality of each compact result, not completion order or elapsed time.

| Deterministic workload check | Observed result |
|---|---:|
| Valid requests / consumers | **12 / 12** |
| Concurrent workers | **8** |
| Aggregate metric partitions selected | **27** |
| Aggregate selected metric files SHA-verified | **27** |
| Unique metric partitions touched | **16** |
| Aggregate response rows | **652** |
| Serial vs concurrent compact results | **exact parity** |
| Serial vs concurrent workload digest | **exact parity** |
| Workload digest | `ef1adcc2dc091ad9ad00c16175ea7b38c8f6fec084c4c1700c6c50c127376e7e` |
| Parallel consumers on the same hot window | **6** |
| Unique full payload hashes across those six | **1** |
| Schema 1.0 vs 1.1 core response SHA for the matched finance query | **exact parity** |

The aggregate count of 27 selected partitions is a deterministic sum of work selected by the 12 requests. It is not a claim that 27 physical reads occurred at the storage layer and it is not a throughput metric.

## Failure isolation

The mixed workload adds three deliberately invalid consumers to the 12 valid requests:

1. an unknown metric;
2. unsupported schema `2.0`;
3. a duplicate metric request.

All three fail through `ReportingContractError`. The validator requires two stronger properties than simply observing those errors:

- every healthy result in the **15-request mixed concurrent workload** must remain identical to its serial baseline;
- after the failure batch completes, replaying all 12 healthy requests must still reproduce the same results.

The observed result is **3/3 intended failures isolated**, with all healthy payload hashes, response hashes, partition selections and row counts preserved both during and after the failures.

## Independent validation

`scripts/validate_workload_isolation_reference.py` does not import the workload harness. It independently:

- parses the serialized request set;
- builds its own serial and `ThreadPoolExecutor` concurrent replays;
- reconciles every successful response back to `incremental_daily_metrics.csv`;
- recomputes the query/data response SHA-256;
- recomputes deterministic partition and row accounting;
- verifies the exact set and type of injected failures;
- checks healthy requests inside the mixed workload and after failure replay.

`results/workload_isolation_reference_summary.csv` pins only deterministic claims. `validate_workload_static_claims.py` rejects attempts to add pinned `seconds`, `latency`, `qps`, `throughput` or `speedup` claims.

## Claim boundary

This evidence supports a specific statement:

> On the pinned single-node DuckDB/Parquet reference, concurrent consumers use independent query connections and reproduce the serial results and deterministic work ledger exactly; invalid consumers fail without changing healthy results.

It does **not** establish:

- a production network-service concurrency SLA;
- requests per second or tail-latency capacity;
- distributed database or object-store isolation;
- admission control, fairness or tenant quotas;
- resource limits under unbounded concurrency;
- behaviour under process, host or network failure.

Those are separate production-system questions. v0.40 intentionally stops before turning a portfolio evidence project into an ungrounded infrastructure benchmark.
