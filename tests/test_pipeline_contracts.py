import duckdb

from product_analytics.config import PRODUCTS
from product_analytics.contracts import event_contract
from product_analytics.generator import generate_events
from product_analytics.metrics import metric_contract_records
from product_analytics.pipeline import run_pipeline


def test_pipeline_persists_auditable_tables(tmp_path):
    raw = generate_events(days=15, seed=23, inject_faults=True)
    database = tmp_path / "workbench.duckdb"
    result = run_pipeline(raw, database_path=database)

    assert len(result["silver_events"]) + len(result["rejected_events"]) == len(raw)
    assert result["quality_report"].rows_rejected == len(result["rejected_events"])
    assert "app_open" in set(result["silver_events"]["event_type"])
    assert "ingested_at" in result["silver_events"].columns
    assert result["silver_events"]["ingested_at"].ge(result["silver_events"]["event_ts"]).all()
    assert {"dau", "dau_legacy_any_event", "dau_definition_delta"}.issubset(
        result["gold_daily_metrics"].columns
    )

    con = duckdb.connect(str(database), read_only=True)
    try:
        tables = {row[0] for row in con.execute("SHOW TABLES").fetchall()}
    finally:
        con.close()

    assert {
        "bronze_events",
        "silver_events",
        "rejected_events",
        "gold_daily_metrics",
        "revenue_reconciliation",
        "quality_report",
    }.issubset(tables)


def test_event_contract_matches_current_config():
    contract = event_contract()
    assert contract["version"] == "1.2"
    assert contract["activity_event"] == "app_open"
    assert contract["generated_processing_time_column"] == "ingested_at"
    fallback = contract["legacy_processing_time_fallback"]
    assert "ingested_at" in fallback and "event_ts" in fallback
    assert set(contract["allowed_products"]) == {product.name for product in PRODUCTS}
    assert set(contract["allowed_event_types"]) == {
        "first_open",
        "app_open",
        "trial_start",
        "paid_subscription",
        "purchase",
    }
    assert "revenue_scope" in contract["rules"]
    assert "active_use" in contract["rules"]
    assert "ingested_at" in contract["rules"]


def test_metric_contracts_are_versioned_and_distinct():
    contracts = {row["name"]: row for row in metric_contract_records()}
    assert set(contracts) == {
        "daily_active_users",
        "daily_active_users_legacy_any_event",
        "paid_conversion_from_first_open",
        "paid_conversion_from_trial_start",
    }
    assert contracts["daily_active_users"]["version"] == "2.0"
    assert "deprecated" in contracts["daily_active_users_legacy_any_event"]["version"]
    assert contracts["daily_active_users"]["numerator"] == "unique users with app_open"
    assert contracts["paid_conversion_from_first_open"]["denominator"] != contracts[
        "paid_conversion_from_trial_start"
    ]["denominator"]
