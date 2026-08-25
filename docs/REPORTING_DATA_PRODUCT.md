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

The reporting layer does not trust a Parquet file merely because it exists. Before a selected month is exposed it checks:

1. the canonical source partition SHA and row count in durable state still match the pinned source manifest;
2. the metric partition is marked complete;
3. the materialised metric file exists; and
4. its SHA-256 still matches durable state.

This ordering applies even to the first and last metric partitions used during store initialisation to determine historical availability. The checksum/state binding is validated **before DuckDB is allowed to open those files**.

That ordering was strengthened by CI. The first implementation corrupted a boundary Parquet in a test but attempted to read it for date bounds before checking its metric SHA, so DuckDB raised its own `InvalidInputException`. The fix moved integrity validation ahead of every boundary read. The revised test now fails closed with `ReportingContractError` during store construction, while a separate real-data test corrupts the middle `2010-12` partition and proves query-time rejection on a normally selected month.

The lesson is stronger than merely having a checksum somewhere in the code path: **integrity checks must precede the parser/query-engine read they are meant to guard**.

## Real-data evidence

The pinned source produces 25 monthly metric partitions over historical availability **2009-12-01 through 2011-12-09**. The reference seven-day query (`2010-12-01` through `2010-12-07`) selects and hashes one relevant metric partition for metric values rather than all 25, a deterministic **96% reduction in metric-partition selection**. The seven returned rows exactly reconcile to the already validated `incremental_daily_metrics.csv` layer. A query spanning the November/December boundary selects exactly two metric partitions.

Store initialisation separately verifies and reads the first/last boundary partitions to establish the available date range. Therefore 96% is not a claim that the entire store lifecycle touches only one file, and it is not a source-row or wall-clock speedup claim.

The reporting evidence is built **after** the v0.37 incremental store exists and does not reparse the XLSX or rebuild the 1,067,371-row canonical source. Stable performance evidence is partition selection/work avoided; GitHub-hosted runner latency remains diagnostic only.

## Response reproducibility

The JSON response includes:

- `schema_version` and `data_product_version`;
- normalised start/end/metric request;
- historical availability and the explicit no-ingestion-time boundary;
- selected partition source and metric SHA-256 provenance;
- deterministic row count;
- deterministic response SHA-256; and
- zero-filled daily records.

The independent validator reconstructs the reference rows directly from `incremental_daily_metrics.csv`, recomputes the response digest without importing the reporting module, checks selected source/state/metric bindings and compares the generated evidence to the checked-in reporting claim ledger.

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
