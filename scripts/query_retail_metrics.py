from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path
import json
import sys

import pandas as pd

from product_analytics.consumer_contract_evolution import (
    DEFAULT_RESPONSE_SCHEMA_VERSION,
    SUPPORTED_RESPONSE_SCHEMA_VERSIONS,
)
from product_analytics.reporting_product import MetricQuery, RetailMetricStore


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Query the versioned UCI retail metric data product"
    )
    parser.add_argument(
        "--incremental-dir",
        type=Path,
        default=Path("build/incremental-retail"),
    )
    parser.add_argument("--start", type=date.fromisoformat, required=True)
    parser.add_argument("--end", type=date.fromisoformat, required=True)
    parser.add_argument(
        "--metrics",
        required=True,
        help="Comma-separated allowlisted metric names",
    )
    parser.add_argument("--format", choices=("json", "csv"), default="json")
    parser.add_argument(
        "--schema-version",
        choices=SUPPORTED_RESPONSE_SCHEMA_VERSIONS,
        default=DEFAULT_RESPONSE_SCHEMA_VERSION,
        help=(
            "JSON response schema to negotiate. The default remains 1.0 for "
            "backward compatibility; CSV always emits the stable date/metric row projection."
        ),
    )
    args = parser.parse_args()

    root = args.incremental_dir
    metrics = tuple(
        name.strip() for name in args.metrics.split(",") if name.strip()
    )
    query = MetricQuery(args.start, args.end, metrics)
    with RetailMetricStore(
        root / "metric_partitions",
        root / "incremental_state.json",
        root / "incremental_source_partition_manifest.csv",
    ) as store:
        response, _ = store.query(query, schema_version=args.schema_version)

    if args.format == "json":
        json.dump(response, sys.stdout, indent=2, sort_keys=True)
        sys.stdout.write("\n")
    else:
        pd.DataFrame(response["data"]).to_csv(sys.stdout, index=False)


if __name__ == "__main__":
    main()
