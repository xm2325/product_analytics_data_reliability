from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from hashlib import sha256
import json
from typing import Iterable, Mapping


SCHEMA_FAMILY = "retail-daily-metrics"
DEFAULT_RESPONSE_SCHEMA_VERSION = "1.0"
LATEST_RESPONSE_SCHEMA_VERSION = "1.1"
SUPPORTED_RESPONSE_SCHEMA_VERSIONS = (
    DEFAULT_RESPONSE_SCHEMA_VERSION,
    LATEST_RESPONSE_SCHEMA_VERSION,
)


@dataclass(frozen=True)
class ResponseSchemaSpec:
    version: str
    top_level_fields: tuple[tuple[str, str], ...]
    query_fields: tuple[tuple[str, str], ...]
    availability_fields: tuple[tuple[str, str], ...]
    partition_provenance_fields: tuple[tuple[str, str], ...]
    row_base_fields: tuple[tuple[str, str], ...]
    metric_types: tuple[tuple[str, str], ...]
    contract_fields: tuple[tuple[str, str], ...] = ()

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        for key in (
            "top_level_fields",
            "query_fields",
            "availability_fields",
            "partition_provenance_fields",
            "row_base_fields",
            "metric_types",
            "contract_fields",
        ):
            payload[key] = [list(item) for item in payload[key]]
        return payload


@dataclass(frozen=True)
class SchemaChangeClassification:
    classification: str
    additions: tuple[str, ...]
    breaking_changes: tuple[str, ...]


_BASE_METRIC_TYPES: tuple[tuple[str, str], ...] = (
    ("revenue_gbp", "float"),
    ("orders", "integer"),
    ("units", "float"),
    ("purchase_lines", "integer"),
    ("active_customers", "integer"),
)

_SCHEMA_V1_0 = ResponseSchemaSpec(
    version="1.0",
    top_level_fields=(
        ("schema_version", "string"),
        ("data_product_version", "string"),
        ("dataset", "string"),
        ("query", "object"),
        ("availability", "object"),
        ("partition_provenance", "array"),
        ("row_count", "integer"),
        ("response_sha256", "sha256"),
        ("data", "array"),
    ),
    query_fields=(
        ("start_date", "date"),
        ("end_date", "date"),
        ("metrics", "array[string]"),
    ),
    availability_fields=(
        ("start_date", "date"),
        ("end_date", "date"),
        ("no_ingestion_time_claim", "boolean"),
    ),
    partition_provenance_fields=(
        ("partition_key", "string"),
        ("source_sha256", "sha256"),
        ("metric_sha256", "sha256"),
    ),
    row_base_fields=(("date", "date"),),
    metric_types=_BASE_METRIC_TYPES,
)

_SCHEMA_V1_1 = replace(
    _SCHEMA_V1_0,
    version="1.1",
    top_level_fields=(*_SCHEMA_V1_0.top_level_fields, ("contract", "object")),
    contract_fields=(
        ("schema_family", "string"),
        ("requested_schema_version", "string"),
        ("backward_compatible_via_negotiation", "array[string]"),
        ("metric_catalog_sha256", "sha256"),
    ),
)


_SCHEMA_BY_VERSION = {
    _SCHEMA_V1_0.version: _SCHEMA_V1_0,
    _SCHEMA_V1_1.version: _SCHEMA_V1_1,
}


def get_response_schema(version: str) -> ResponseSchemaSpec:
    try:
        return _SCHEMA_BY_VERSION[version]
    except KeyError as exc:
        raise ValueError(
            f"unsupported reporting schema version {version!r}; "
            f"supported={list(SUPPORTED_RESPONSE_SCHEMA_VERSIONS)}"
        ) from exc


def response_schema_registry() -> dict[str, object]:
    return {
        "schema_family": SCHEMA_FAMILY,
        "default_schema_version": DEFAULT_RESPONSE_SCHEMA_VERSION,
        "latest_schema_version": LATEST_RESPONSE_SCHEMA_VERSION,
        "supported_schema_versions": list(SUPPORTED_RESPONSE_SCHEMA_VERSIONS),
        "default_migration_policy": (
            "do not silently move existing consumers to a newer schema; "
            "new schema versions require explicit negotiation"
        ),
        "schemas": [
            get_response_schema(version).to_dict()
            for version in SUPPORTED_RESPONSE_SCHEMA_VERSIONS
        ],
    }


def _field_map(fields: Iterable[tuple[str, str]]) -> dict[str, str]:
    return dict(fields)


def classify_schema_change(
    base: ResponseSchemaSpec,
    candidate: ResponseSchemaSpec,
) -> SchemaChangeClassification:
    additions: list[str] = []
    breaking: list[str] = []

    sections = (
        ("top_level", base.top_level_fields, candidate.top_level_fields),
        ("query", base.query_fields, candidate.query_fields),
        ("availability", base.availability_fields, candidate.availability_fields),
        (
            "partition_provenance",
            base.partition_provenance_fields,
            candidate.partition_provenance_fields,
        ),
        ("row", base.row_base_fields, candidate.row_base_fields),
        ("metric", base.metric_types, candidate.metric_types),
    )
    for section, old_fields, new_fields in sections:
        old = _field_map(old_fields)
        new = _field_map(new_fields)
        for name, old_type in old.items():
            if name not in new:
                breaking.append(f"{section}.{name}:removed")
            elif new[name] != old_type:
                breaking.append(
                    f"{section}.{name}:type:{old_type}->{new[name]}"
                )
        for name in sorted(set(new) - set(old)):
            additions.append(f"{section}.{name}")

    if base.contract_fields:
        old_contract = _field_map(base.contract_fields)
        new_contract = _field_map(candidate.contract_fields)
        for name, old_type in old_contract.items():
            if name not in new_contract:
                breaking.append(f"contract.{name}:removed")
            elif new_contract[name] != old_type:
                breaking.append(
                    f"contract.{name}:type:{old_type}->{new_contract[name]}"
                )
        for name in sorted(set(new_contract) - set(old_contract)):
            additions.append(f"contract.{name}")
    elif candidate.contract_fields:
        additions.extend(
            f"contract.{name}" for name, _ in candidate.contract_fields
        )

    if breaking:
        kind = "BREAKING"
    elif additions:
        kind = "ADDITIVE"
    else:
        kind = "IDENTICAL"
    return SchemaChangeClassification(
        classification=kind,
        additions=tuple(sorted(additions)),
        breaking_changes=tuple(sorted(breaking)),
    )


def _candidate_replace_field(
    schema: ResponseSchemaSpec,
    *,
    section: str,
    old_name: str,
    new_name: str | None = None,
    new_type: str | None = None,
    version: str,
) -> ResponseSchemaSpec:
    attr = {
        "top_level": "top_level_fields",
        "metric": "metric_types",
    }[section]
    fields = list(getattr(schema, attr))
    updated: list[tuple[str, str]] = []
    found = False
    for name, dtype in fields:
        if name != old_name:
            updated.append((name, dtype))
            continue
        found = True
        if new_name is not None:
            updated.append((new_name, new_type or dtype))
        elif new_type is not None:
            updated.append((name, new_type))
    if not found:
        raise ValueError(f"field {old_name!r} not found in {section}")
    return replace(schema, version=version, **{attr: tuple(updated)})


def governed_schema_migrations() -> list[dict[str, object]]:
    base = _SCHEMA_V1_0
    candidates = (
        (
            "add_contract_metadata",
            _SCHEMA_V1_1,
            "Expose deterministic contract metadata only to consumers that explicitly request schema 1.1.",
        ),
        (
            "rename_row_count_to_rows",
            _candidate_replace_field(
                base,
                section="top_level",
                old_name="row_count",
                new_name="rows",
                version="2.0-candidate",
            ),
            "Renaming a published top-level field can break existing consumers.",
        ),
        (
            "change_orders_integer_to_float",
            _candidate_replace_field(
                base,
                section="metric",
                old_name="orders",
                new_type="float",
                version="2.0-candidate-orders-float",
            ),
            "Changing a published metric type can break parsing and downstream validation.",
        ),
    )
    rows: list[dict[str, object]] = []
    for name, candidate, rationale in candidates:
        classification = classify_schema_change(base, candidate)
        action = "APPROVE" if classification.classification == "ADDITIVE" else "WITHHOLD"
        rows.append(
            {
                "proposal": name,
                "base_version": base.version,
                "candidate_version": candidate.version,
                "classification": classification.classification,
                "action": action,
                "additions": list(classification.additions),
                "breaking_changes": list(classification.breaking_changes),
                "rationale": rationale,
                "candidate_schema": candidate.to_dict(),
            }
        )
    return rows


def metric_catalog_sha256(catalog: list[dict[str, str]]) -> str:
    canonical = json.dumps(catalog, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )
    return sha256(canonical).hexdigest()


def contract_metadata(catalog: list[dict[str, str]]) -> dict[str, object]:
    return {
        "schema_family": SCHEMA_FAMILY,
        "requested_schema_version": LATEST_RESPONSE_SCHEMA_VERSION,
        "backward_compatible_via_negotiation": [
            DEFAULT_RESPONSE_SCHEMA_VERSION
        ],
        "metric_catalog_sha256": metric_catalog_sha256(catalog),
    }


def _expect_fields(
    payload: Mapping[str, object],
    fields: tuple[tuple[str, str], ...],
    *,
    label: str,
    exact: bool = False,
) -> None:
    expected = {name for name, _ in fields}
    observed = set(payload)
    missing = expected - observed
    if missing:
        raise ValueError(f"{label} missing fields: {sorted(missing)}")
    if exact:
        extra = observed - expected
        if extra:
            raise ValueError(f"{label} has unexpected fields: {sorted(extra)}")


def validate_response_shape(
    response: Mapping[str, object],
    *,
    schema_version: str,
    requested_metrics: tuple[str, ...],
    strict_top_level: bool = True,
) -> None:
    schema = get_response_schema(schema_version)
    _expect_fields(
        response,
        schema.top_level_fields,
        label=f"schema {schema_version} response",
        exact=strict_top_level,
    )
    if response.get("schema_version") != schema_version:
        raise ValueError(
            f"response schema_version={response.get('schema_version')!r} "
            f"does not match requested {schema_version!r}"
        )

    query = response.get("query")
    availability = response.get("availability")
    provenance = response.get("partition_provenance")
    data = response.get("data")
    if not isinstance(query, Mapping):
        raise ValueError("query must be an object")
    if not isinstance(availability, Mapping):
        raise ValueError("availability must be an object")
    if not isinstance(provenance, list):
        raise ValueError("partition_provenance must be an array")
    if not isinstance(data, list):
        raise ValueError("data must be an array")
    _expect_fields(query, schema.query_fields, label="query", exact=True)
    _expect_fields(
        availability,
        schema.availability_fields,
        label="availability",
        exact=True,
    )
    for index, row in enumerate(provenance):
        if not isinstance(row, Mapping):
            raise ValueError(f"partition_provenance[{index}] must be an object")
        _expect_fields(
            row,
            schema.partition_provenance_fields,
            label=f"partition_provenance[{index}]",
            exact=True,
        )

    allowed_metric_types = dict(schema.metric_types)
    for metric in requested_metrics:
        if metric not in allowed_metric_types:
            raise ValueError(f"metric {metric!r} is absent from schema {schema_version}")
    expected_row_fields = {"date", *requested_metrics}
    for index, row in enumerate(data):
        if not isinstance(row, Mapping):
            raise ValueError(f"data[{index}] must be an object")
        if set(row) != expected_row_fields:
            raise ValueError(
                f"data[{index}] fields={sorted(row)} expected={sorted(expected_row_fields)}"
            )

    if schema.contract_fields:
        contract = response.get("contract")
        if not isinstance(contract, Mapping):
            raise ValueError("schema 1.1 contract metadata must be an object")
        _expect_fields(
            contract,
            schema.contract_fields,
            label="contract",
            exact=True,
        )
