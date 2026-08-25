from __future__ import annotations

from product_analytics.consumer_contract_evolution import (
    DEFAULT_RESPONSE_SCHEMA_VERSION,
    LATEST_RESPONSE_SCHEMA_VERSION,
    classify_schema_change,
    get_response_schema,
    governed_schema_migrations,
    response_schema_registry,
)


def test_registry_keeps_existing_consumers_on_1_0_by_default() -> None:
    registry = response_schema_registry()
    assert registry["default_schema_version"] == DEFAULT_RESPONSE_SCHEMA_VERSION == "1.0"
    assert registry["latest_schema_version"] == LATEST_RESPONSE_SCHEMA_VERSION == "1.1"
    assert registry["supported_schema_versions"] == ["1.0", "1.1"]


def test_published_1_1_is_additive_over_1_0() -> None:
    result = classify_schema_change(
        get_response_schema("1.0"),
        get_response_schema("1.1"),
    )
    assert result.classification == "ADDITIVE"
    assert result.breaking_changes == ()
    assert "top_level.contract" in result.additions


def test_governance_approves_only_additive_candidate() -> None:
    decisions = {row["proposal"]: row for row in governed_schema_migrations()}
    assert decisions["add_contract_metadata"]["action"] == "APPROVE"
    assert decisions["add_contract_metadata"]["classification"] == "ADDITIVE"
    assert decisions["rename_row_count_to_rows"]["action"] == "WITHHOLD"
    assert decisions["rename_row_count_to_rows"]["classification"] == "BREAKING"
    assert decisions["change_orders_integer_to_float"]["action"] == "WITHHOLD"
    assert decisions["change_orders_integer_to_float"]["classification"] == "BREAKING"


def test_breaking_reasons_are_field_specific() -> None:
    decisions = {row["proposal"]: row for row in governed_schema_migrations()}
    rename = decisions["rename_row_count_to_rows"]["breaking_changes"]
    dtype = decisions["change_orders_integer_to_float"]["breaking_changes"]
    assert "top_level.row_count:removed" in rename
    assert "metric.orders:type:integer->float" in dtype
