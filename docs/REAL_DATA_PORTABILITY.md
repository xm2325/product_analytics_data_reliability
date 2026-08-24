# Real-data portability (v0.36)

v0.36 adds an external-data evidence lane using **UCI Online Retail II** rather than extending the synthetic generator. UCI describes the dataset as real transactions from a UK-based registered non-store online retailer between 1 December 2009 and 9 December 2011. The source contains 1,067,371 transaction rows and is distributed under CC BY 4.0 (DOI `10.24432/C5CG6D`).

## Why this lane exists

The synthetic reference remains useful for controlled failure injection, point-in-time evidence and decision-boundary tests. It cannot by itself show that the code handles an externally designed schema, missing identities, cancellations, returns and business-day gaps that were not generated to match the workbench.

The real-data lane therefore tests portability rather than claiming a production deployment:

```text
official external source
    -> source adapter
    -> explicit quality report
    -> source-specific metric contract
    -> continuous daily metric table
    -> semantic replacement check
    -> frozen leakage-safe forecast contract
    -> independent recomputation
```

## Source and reproducibility

The workflow downloads the official UCI ZIP directly from:

`https://archive.ics.uci.edu/static/public/502/online%2Bretail%2Bii.zip`

The repository does **not** commit the source workbook. Each run records archive and workbook byte sizes plus SHA-256 digests, then uploads only compact derived evidence. This keeps source provenance auditable without turning the repository into a mirror of the dataset.

The source adapter accepts the field names used by both workbook vintages (`Invoice`/`InvoiceNo`, `Price`/`UnitPrice`, `Customer ID`/`CustomerID`) and maps them to one canonical transaction model.

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

## Semantic replacement check

The lane deliberately distinguishes a valid alternative metric from a backward-compatible replacement.

For example, signed transaction value including cancellations/returns can be a useful *net ledger* metric. It is not automatically safe to substitute for a previously published *positive non-cancelled purchase revenue* metric under the same name. v0.36 quantifies the difference and applies the same declared 1% backward-compatibility tolerance used for governed semantic changes.

A failure therefore means **WITHHOLD AS DROP-IN REPLACEMENT**, not “the alternative metric is wrong”.

## Forecast portability

v0.36 reuses the v0.35 forecasting contract without tuning it to the UCI dataset:

- weekly seasonal-naive candidate, lag 7;
- last-observation benchmark;
- four rolling origins × seven-day horizon;
- MAPE and WAPE ≤ 20%;
- candidate WAPE no worse than the benchmark;
- empirical coverage ≥ 85% for the nominal 90% residual interval;
- no future seasonal source is allowed.

The purpose is to test whether the decision system remains honest on external data. A real series is allowed to fail the gate; the workflow must report that failure rather than retune thresholds after seeing the result.

## Explicit boundary: no ingestion-time claim

Online Retail II exposes invoice/event time but not a separate processing or ingestion timestamp. The v0.36 real-data lane therefore does **not** claim to validate late-arrival, watermark, backfill or processing-time SLA behaviour on this source. Those capabilities remain controlled synthetic evidence in v0.35.

This separation is intentional: external validity should not be purchased by inventing fields that the real source does not contain.
