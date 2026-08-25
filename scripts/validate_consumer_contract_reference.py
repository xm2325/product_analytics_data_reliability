from __future__ import annotations

import argparse
from hashlib import sha256
from pathlib import Path
import json

import pandas as pd


EXPECTED_LEDGER = Path("results/consumer_contract_reference_summary.csv")


def _pairs(payload: dict[str, object], key: str) -> dict[str, str]:
    value = payload.get(key)
    if not isinstance(value, list):
        raise AssertionError(f"schema section {key!r} is not a list")
    output: dict[str, str] = {}
    for item in value:
        if not isinstance(item, list) or len(item) != 2:
            raise AssertionError(f"invalid schema field entry in {key!r}: {item!r}")
        name, dtype = item
        if not isinstance(name, str) or not isinstance(dtype, str):
            raise AssertionError(f"invalid schema field types in {key!r}: {item!r}")
        if name in output:
            raise AssertionError(f"duplicate field {name!r} in schema section {key!r}")
        output[name] = dtype
    return output


def _classify(base: dict[str, object], candidate: dict[str, object]) -> tuple[str, list[str], list[str]]:
    additions: list[str] = []
    breaking: list[str] = []
    for label, key in (
        ("top_level", "top_level_fields"),
        ("query", "query_fields"),
        ("availability", "availability_fields"),
        ("partition_provenance", "partition_provenance_fields"),
        ("row", "row_base_fields"),
        ("metric", "metric_types"),
    ):
        old = _pairs(base, key)
        new = _pairs(candidate, key)
        for name, dtype in old.items():
            if name not in new:
                breaking.append(f"{label}.{name}:removed")
            elif new[name] != dtype:
                breaking.append(f"{label}.{name}:type:{dtype}->{new[name]}")
        additions.extend(f"{label}.{name}" for name in sorted(set(new) - set(old)))

    old_contract = _pairs(base, "contract_fields")
    new_contract = _pairs(candidate, "contract_fields")
    for name, dtype in old_contract.items():
        if name not in new_contract:
            breaking.append(f"contract.{name}:removed")
        elif new_contract[name] != dtype:
            breaking.append(f"contract.{name}:type:{dtype}->{new_contract[name]}")
    additions.extend(f"contract.{name}" for name in sorted(set(new_contract) - set(old_contract)))

    classification = "BREAKING" if breaking else "ADDITIVE" if additions else "IDENTICAL"
    return classification, sorted(additions), sorted(breaking)


def _response_digest(response: dict[str, object]) -> str:
    canonical = json.dumps(
        {"query": response["query"], "data": response["data"]},
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return sha256(canonical).hexdigest()


def _catalog_digest(catalog: list[dict[str, str]]) -> str:
    canonical = json.dumps(catalog, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return sha256(canonical).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Independently validate v0.39 consumer contract evolution evidence"
    )
    parser.add_argument("incremental_dir", type=Path)
    parser.add_argument("--ledger", type=Path, default=EXPECTED_LEDGER)
    args = parser.parse_args()
    root = args.incremental_dir

    registry = json.loads((root / "consumer_contract_schema_registry.json").read_text())
    migrations = json.loads((root / "consumer_contract_migrations.json").read_text())
    v1_0 = json.loads((root / "consumer_contract_sample_v1_0.json").read_text())
    v1_1 = json.loads((root / "consumer_contract_sample_v1_1.json").read_text())
    evidence = json.loads((root / "consumer_contract_evidence.json").read_text())
    catalog = json.loads((root / "reporting_metric_catalog.json").read_text())

    if registry["schema_family"] != "retail-daily-metrics":
        raise AssertionError("Unexpected schema family")
    if registry["default_schema_version"] != "1.0":
        raise AssertionError("Existing consumers were silently moved off schema 1.0")
    if registry["latest_schema_version"] != "1.1":
        raise AssertionError("Unexpected latest consumer schema")
    if registry["supported_schema_versions"] != ["1.0", "1.1"]:
        raise AssertionError("Unexpected supported schema versions")

    schemas = {row["version"]: row for row in registry["schemas"]}
    if set(schemas) != {"1.0", "1.1"}:
        raise AssertionError(f"Unexpected published schema registry: {sorted(schemas)}")
    published_classification, published_additions, published_breaking = _classify(
        schemas["1.0"], schemas["1.1"]
    )
    if published_classification != "ADDITIVE" or published_breaking:
        raise AssertionError(
            f"Published schema 1.1 is not additive: additions={published_additions}, breaking={published_breaking}"
        )
    if "top_level.contract" not in published_additions:
        raise AssertionError("Schema 1.1 did not add the declared contract envelope")

    expected_v1_0_top = set(_pairs(schemas["1.0"], "top_level_fields"))
    expected_v1_1_top = set(_pairs(schemas["1.1"], "top_level_fields"))
    if set(v1_0) != expected_v1_0_top:
        raise AssertionError("Negotiated schema 1.0 response does not match its strict top-level contract")
    if set(v1_1) != expected_v1_1_top:
        raise AssertionError("Negotiated schema 1.1 response does not match its strict top-level contract")
    if v1_0["schema_version"] != "1.0" or v1_1["schema_version"] != "1.1":
        raise AssertionError("Negotiated response schema version mismatch")
    if v1_0["query"] != v1_1["query"] or v1_0["data"] != v1_1["data"]:
        raise AssertionError("Schema negotiation changed query semantics or returned data")
    if v1_0["response_sha256"] != v1_1["response_sha256"]:
        raise AssertionError("Schema negotiation changed the stable query/data response hash")
    if v1_0["response_sha256"] != _response_digest(v1_0):
        raise AssertionError("Schema 1.0 response hash does not independently recompute")
    if v1_1["response_sha256"] != _response_digest(v1_1):
        raise AssertionError("Schema 1.1 response hash does not independently recompute")

    contract = v1_1.get("contract")
    if not isinstance(contract, dict):
        raise AssertionError("Schema 1.1 response has no contract metadata")
    if contract.get("schema_family") != registry["schema_family"]:
        raise AssertionError("Schema 1.1 contract family mismatch")
    if contract.get("requested_schema_version") != "1.1":
        raise AssertionError("Schema 1.1 contract did not record the negotiated version")
    if contract.get("backward_compatible_via_negotiation") != ["1.0"]:
        raise AssertionError("Schema 1.1 did not preserve explicit 1.0 negotiation")
    if contract.get("metric_catalog_sha256") != _catalog_digest(catalog):
        raise AssertionError("Schema 1.1 metric catalog digest mismatch")

    if len(migrations) != 3:
        raise AssertionError(f"Expected three governed migrations, got {len(migrations)}")
    base = schemas["1.0"]
    actions: dict[str, str] = {}
    for row in migrations:
        classification, additions, breaking = _classify(base, row["candidate_schema"])
        if classification != row["classification"]:
            raise AssertionError(
                f"Migration {row['proposal']} classification mismatch: generated={row['classification']}, independent={classification}"
            )
        if additions != sorted(row["additions"]):
            raise AssertionError(f"Migration {row['proposal']} additive diff mismatch")
        if breaking != sorted(row["breaking_changes"]):
            raise AssertionError(f"Migration {row['proposal']} breaking diff mismatch")
        expected_action = "APPROVE" if classification == "ADDITIVE" else "WITHHOLD"
        if row["action"] != expected_action:
            raise AssertionError(
                f"Migration {row['proposal']} action={row['action']} expected={expected_action}"
            )
        actions[row["proposal"]] = row["action"]

    if actions != {
        "add_contract_metadata": "APPROVE",
        "rename_row_count_to_rows": "WITHHOLD",
        "change_orders_integer_to_float": "WITHHOLD",
    }:
        raise AssertionError(f"Unexpected migration decisions: {actions}")

    ledger = pd.read_csv(args.ledger, dtype=str)
    if ledger["claim"].duplicated().any():
        raise AssertionError("Duplicate consumer contract claim keys")
    claims = dict(zip(ledger["claim"], ledger["value"]))
    generated = {
        "version": str(evidence["version"]),
        "schema_family": str(evidence["schema_family"]),
        "default_schema_version": str(evidence["default_schema_version"]),
        "latest_schema_version": str(evidence["latest_schema_version"]),
        "supported_schema_versions": str(evidence["supported_schema_versions"]),
        "no_silent_default_migration": str(bool(evidence["no_silent_default_migration"])).lower(),
        "v1_0_default_preserved": str(bool(evidence["v1_0_default_preserved"])).lower(),
        "v1_0_v1_1_data_parity": str(bool(evidence["v1_0_v1_1_data_parity"])).lower(),
        "v1_0_v1_1_query_parity": str(bool(evidence["v1_0_v1_1_query_parity"])).lower(),
        "v1_0_v1_1_response_sha_parity": str(bool(evidence["v1_0_v1_1_response_sha_parity"])).lower(),
        "v1_0_v1_1_work_parity": str(bool(evidence["v1_0_v1_1_work_parity"])).lower(),
        "v1_1_contract_metadata_present": str(bool(evidence["v1_1_contract_metadata_present"])).lower(),
        "unsupported_schema_rejected": str(bool(evidence["unsupported_schema_rejected"])).lower(),
        "migration_proposals": str(evidence["migration_proposals"]),
        "approved_additive_migrations": str(evidence["approved_additive_migrations"]),
        "withheld_breaking_migrations": str(evidence["withheld_breaking_migrations"]),
    }
    for key, expected in generated.items():
        if claims.get(key) != expected:
            raise AssertionError(
                f"Consumer contract claim {key!r}: ledger={claims.get(key)!r}, generated={expected!r}"
            )

    print(
        "Consumer contract validation passed: "
        f"schemas={registry['supported_schema_versions']}, actions={actions}, "
        f"rows={v1_0['row_count']}"
    )


if __name__ == "__main__":
    main()
