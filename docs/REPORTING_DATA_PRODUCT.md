# Reporting data product contract

v0.38 adds a consumer-facing reporting boundary over the v0.37 incremental UCI Online Retail II metric store. It is deliberately a small Python/CLI data product rather than a web framework demo: the stable contract is metric semantics, query validation, provenance and deterministic work selection. A network transport can be added later without redefining the metrics.

## Consumer contract

The interface exposes five daily metrics:

- `revenue_gbp`
- `orders`
- `units`
- `purchase_lines`
- `active_customers`

Every JSON response includes schema/data-product versions, the normalised query, available historical date range, selected partition provenance, row count, a deterministic response SHA-256 and the data rows. Missing calendar days are returned explicitly with zero values so consumers do not need to infer whether a missing row means zero activity or missing output.

The request surface is intentionally bounded:

- only catalogued metric names are accepted;
- metric names may not be duplicated;
- start must be on or before end;
- the window must stay inside available historical data;
- the maximum request is 366 days;
- only month partitions intersecting the request are read for metric values.

## Integrity before serve

The reporting layer does not trust a Parquet file merely because it exists. For each selected month it checks:

1. the canonical source partition SHA and row count in durable state still match the pinned source manifest;
2. the metric partition is marked complete;
3. the materialised metric file exists; and
4. its SHA-256 still matches durable state.

A deliberately corrupted selected metric partition is therefore rejected before data are served.

## Real-data evidence

The pinned source produces 25 monthly metric partitions. The reference seven-day query (`2010-12-01` through `2010-12-07`) reads and hashes one relevant metric partition rather than all 25, a deterministic 96% reduction in partition selection. The seven returned rows exactly reconcile to the already validated `incremental_daily_metrics.csv` layer. A query spanning the November/December boundary selects exactly two partitions.

This is a metric-store work claim, not a wall-clock SLA. GitHub-hosted runner latency remains diagnostic only.

## Historical-time boundary

UCI Online Retail II contains invoice/event time but no independent ingestion timestamp. The reporting product therefore exposes an available historical date range and **does not** claim point-in-time/as-of reconstruction. That boundary is kept explicit rather than inventing production freshness semantics the source cannot validate.

## CLI

After building the real incremental evidence:

```bash
python scripts/query_retail_metrics.py \
  --incremental-dir build/incremental-retail \
  --start 2010-12-01 \
  --end 2010-12-07 \
  --metrics revenue_gbp,orders,active_customers \
  --format json
```

Use `--format csv` when a tabular consumer does not need the surrounding provenance envelope.
