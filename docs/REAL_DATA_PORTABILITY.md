# Real-data portability (v0.36)

v0.36 adds an external-data evidence lane using **UCI Online Retail II** rather than extending the synthetic generator. UCI describes the dataset as real transactions from a UK-based registered non-store online retailer between 1 December 2009 and 9 December 2011. The source contains **1,067,371 transaction rows** and is distributed under CC BY 4.0 (DOI `10.24432/C5CG6D`).

## Why this lane exists

The synthetic reference remains useful for controlled failure injection, point-in-time evidence and decision-boundary tests. It cannot by itself show that the code handles an externally designed schema, missing identities, cancellations, returns and business-day gaps that were not generated to match the workbench.

The real-data lane therefore tests portability rather than claiming a production deployment:

```text
official external source
    -> pinned source hash
    -> source adapter
    -> explicit quality report
    -> source-specific metric contract
    -> continuous daily metric table
    -> semantic replacement check
    -> frozen leakage-safe forecast contract
    -> independent DuckDB/Python recomputation
    -> checked-in public claim ledger
```

## Source and reproducibility

The workflow downloads the official UCI ZIP directly from the UCI archive. The repository does **not** commit the source workbook. Instead, the source boundary is pinned before any analysis:

```text
archive bytes   = 45,622,418
archive SHA-256 = 572e36277c2390fbfde10664750731e0a86f55e33470d91919085f0408e67bfb
workbook bytes  = 45,622,278
workbook SHA-256= bcbe73b35f5b7babf197fb0cb983a11f5d9ff929078d4aa53d171b1f2df2e980
```

An upstream source change therefore fails the build and requires explicit review instead of silently moving the public reference. Only compact derived evidence is uploaded from CI.

The source adapter accepts the field names used by both workbook vintages (`Invoice`/`InvoiceNo`, `Price`/`UnitPrice`, `Customer ID`/`CustomerID`) and maps them to one canonical transaction model.

## Real-data reference quality

The validated reference spans **739 calendar days** and independently reproduces these source characteristics:

| Check | Result |
|---|---:|
| Source rows | **1,067,371** |
| Purchase-line rows under the declared contract | **1,041,670** |
| Missing CustomerID rows | **243,007** |
| Cancellation rows | **19,494** |
| Non-positive quantity rows | **22,950** |
| Non-positive unit-price rows | **6,207** |
| Exact duplicate rows excluding generated source-row ID | **12,133** |
| Distinct invoices | **53,628** |
| Distinct stock codes | **5,304** |
| Countries | **43** |

The first real-data CI exposed a concrete portability bug: a purchase day containing only anonymous customers produced `NaN` active customers after the identity join. The implementation was corrected to encode the business meaning as **0 identifiable active customers**, rather than weakening the test to accept `NaN`.

## Metric contract

A valid purchase line requires all of the following:

```text
invoice timestamp present
AND invoice is not marked as a cancellation
AND quantity > 0
AND unit price > 0
```

The real-data daily metrics are:

- `revenue_gbp`: sum of quantity × unit price over valid purchase lines;
- `orders`: unique invoice numbers among valid purchase lines;
- `units`: quantity over valid purchase lines;
- `purchase_lines`: count of valid purchase lines;
- `active_customers`: unique non-null customer IDs among valid purchase lines.

Missing customer IDs do not invalidate otherwise valid purchase lines; they are excluded only from the customer-identity metric. Calendar days without valid purchases are explicit zero rows rather than silently disappearing from the time series.

## Semantic replacement evidence

The lane deliberately distinguishes a valid alternative metric from a backward-compatible replacement.

| Proposed drop-in replacement | Current | Candidate | Relative shift | 1% compatibility result |
|---|---:|---:|---:|---|
| Purchase revenue -> signed transaction ledger | £20,972,594.57 | £19,287,250.57 | **-8.04%** | **WITHHOLD** |
| Purchasing-customer population -> any-transaction customer population | 5,878 | 5,942 | **+1.09%** | **WITHHOLD** |

Signed transaction value including cancellations/returns can be a useful *net ledger* metric. The decision above does not label it wrong; it says an **8.04%** change cannot silently replace the previously declared purchase-revenue metric under the same name. The customer definition is a closer case but still crosses the pre-declared 1% compatibility tolerance.

## Frozen forecast portability

v0.36 reuses the v0.35 forecasting contract without tuning it to the UCI dataset:

- weekly seasonal-naive candidate, lag 7;
- last-observation benchmark;
- four rolling origins × seven-day horizon;
- MAPE and WAPE ≤ 20%;
- candidate WAPE no worse than the benchmark;
- empirical coverage ≥ 85% for the nominal 90% residual interval;
- no future seasonal source is allowed.

The real data are intentionally allowed to fail. All four candidate forecasts beat the last-value benchmark on WAPE and clear the interval-coverage gate, but **0/4 are planning-approved** because the frozen absolute-accuracy contract is non-compensatory:

| Metric | MAPE | WAPE | Last-value WAPE | Interval coverage | Decision |
|---|---:|---:|---:|---:|---|
| revenue_gbp | **25.28%** | **28.50%** | 45.18% | 85.7% | **WITHHOLD** |
| orders | **20.94%** | 15.31% | 37.35% | 89.3% | **WITHHOLD** |
| units | **26.20%** | **29.34%** | 46.55% | 92.9% | **WITHHOLD** |
| active_customers | **22.79%** | 17.03% | 37.34% | 92.9% | **WITHHOLD** |

`orders` is the useful boundary example: its WAPE is only **15.31%** and the candidate beats the last-value benchmark by about **59%**, but MAPE is **20.94%**, just above the pre-existing 20% limit. v0.36 does not retune the limit after seeing the real data; the decision remains **WITHHOLD**.

## Independent validation and public claims

`validate_real_retail_reference.py` re-extracts the pinned workbook, reloads all 1,067,371 rows, recomputes source-quality counts and daily metrics in DuckDB SQL, and independently recomputes the semantic and forecast decisions. `validate_real_static_claims.py` then binds the generated evidence to `results/real_data_reference_summary.csv`, so changing a public result requires an explicit reviewed ledger update.

## Explicit boundary: no ingestion-time claim

Online Retail II exposes invoice/event time but not a separate processing or ingestion timestamp. The v0.36 real-data lane therefore does **not** claim to validate late-arrival, watermark, backfill or processing-time SLA behaviour on this source. Those capabilities remain controlled synthetic evidence in v0.35.

This separation is intentional: external validity should not be purchased by inventing fields that the real source does not contain.
