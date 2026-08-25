from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path
import json

from product_analytics.consumer_contract_evolution import (
    DEFAULT_RESPONSE_SCHEMA_VERSION,
    LATEST_RESPONSE_SCHEMA_VERSION,
    governed_schema_migrations,
    response_schema_registry,
    validate_response_shape,
)
from product_analytics.reporting_product import (
    MetricQuery,
    ReportingContractError,
    RetailMetricStore,
)


def _write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build v0.39 negotiated consumer-contract evolution evidence"
    )
    parser.add_argument(
        "--incremental-dir",
        type=Path,
        default=Path("build/incremental-retail"),
    )
    args = parser.parse_args()
    root = args.incremental_dir

    metric_dir = root / "metric_partitions"
    state_path = root / "incremental_state.json"
    source_manifest_path = root / "incremental_source_partition_manifest.csv"
    for required in (metric_dir, state_path, source_manifest_path):
        if not required.exists():
            raise FileNotFoundError(required)

    query = MetricQuery(
        start_date=date(2010, 12, 1),
        end_date=date(2010, 12, 7),
        metrics=(
            "revenue_gbp",
            "orders",
            "units",
            "purchase_lines",
            "active_customers",
        ),
    )

    with RetailMetricStore(metric_dir, state_path, source_manifest_path) as store:
        default_response, default_work = store.query(query)
        v1_1_response, v1_1_work = store.query(
            query,
            schema_version=LATEST_RESPONSE_SCHEMA_VERSION,
        )
        unsupported_schema_rejected = False
        try:
            store.query(query, schema_version="2.0")
        except ReportingContractError:
            unsupported_schema_rejected = True

    if default_response["schema_version"] != DEFAULT_RESPONSE_SCHEMA_VERSION:
        raise AssertionError("Default consumer schema moved silently")
    if v1_1_response["schema_version"] != LATEST_RESPONSE_SCHEMA_VERSION:
        raise AssertionError("Explicit schema 1.1 negotiation failed")
    validate_response_shape(
        default_response,
        schema_version=DEFAULT_RESPONSE_SCHEMA_VERSION,
        requested_metrics=query.metrics,
        strict_top_level=True,
    )
    validate_response_shape(
        v1_1_response,
        schema_version=LATEST_RESPONSE_SCHEMA_VERSION,
        requested_metrics=query.metrics,
        strict_top_level=True,
    )

    v1_0_v1_1_data_parity = default_response["data"] == v1_1_response["data"]
    v1_0_v1_1_query_parity = default_response["query"] == v1_1_response["query"]
    v1_0_v1_1_response_sha_parity = (
        default_response["response_sha256"] == v1_1_response["response_sha256"]
    )
    v1_0_v1_1_work_parity = default_work == v1_1_work
    if not all(
        (
            v1_0_v1_1_data_parity,
            v1_0_v1_1_query_parity,
            v1_0_v1_1_response_sha_parity,
            v1_0_v1_1_work_parity,
        )
    ):
        raise AssertionError("Schema negotiation changed query semantics or work selection")
    if not unsupported_schema_rejected:
        raise AssertionError("Unsupported consumer schema was accepted")

    registry = response_schema_registry()
    migrations = governed_schema_migrations()
    approved = [row for row in migrations if row["action"] == "APPROVE"]
    withheld = [row for row in migrations if row["action"] == "WITHHOLD"]
    if [row["proposal"] for row in approved] != ["add_contract_metadata"]:
        raise AssertionError("Only the governed additive schema migration should be approved")
    if {row["proposal"] for row in withheld} != {
        "rename_row_count_to_rows",
        "change_orders_integer_to_float",
    }:
        raise AssertionError("Breaking consumer schema migrations were not withheld")

    evidence = {
        "version": "0.39.0",
        "schema_family": registry["schema_family"],
        "default_schema_version": registry["default_schema_version"],
        "latest_schema_version": registry["latest_schema_version"],
        "supported_schema_versions": len(registry["supported_schema_versions"]),
        "no_silent_default_migration": True,
        "v1_0_default_preserved": default_response["schema_version"] == "1.0",
        "v1_0_strict_top_level_fields": len(default_response),
        "v1_1_top_level_fields": len(v1_1_response),
        "v1_1_additional_top_level_fields": sorted(
            set(v1_1_response) - set(default_response)
        ),
        "v1_0_v1_1_data_parity": v1_0_v1_1_data_parity,
        "v1_0_v1_1_query_parity": v1_0_v1_1_query_parity,
        "v1_0_v1_1_response_sha_parity": v1_0_v1_1_response_sha_parity,
        "v1_0_v1_1_work_parity": v1_0_v1_1_work_parity,
        "v1_1_contract_metadata_present": "contract" in v1_1_response,
        "unsupported_schema_rejected": unsupported_schema_rejected,
        "migration_proposals": len(migrations),
        "approved_additive_migrations": len(approved),
        "withheld_breaking_migrations": len(withheld),
        "governance_rule": (
            "existing consumers remain on the default schema; additive schemas may be "
            "offered through explicit negotiation, while removals/renames/type changes are withheld"
        ),
    }

    _write_json(root / "consumer_contract_schema_registry.json", registry)
    _write_json(root / "consumer_contract_migrations.json", migrations)
    _write_json(root / "consumer_contract_sample_v1_0.json", default_response)
    _write_json(root / "consumer_contract_sample_v1_1.json", v1_1_response)
    _write_json(root / "consumer_contract_evidence.json", evidence)
    print(json.dumps(evidence, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
