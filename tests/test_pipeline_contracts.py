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
    assert set(contract["allowed_products"]) == {product.name for product in PRODUCTS}
    assert set(contract["allowed_event_types"]) == {
        "first_open",
        "trial_start",
        "paid_subscription",
        "purchase",
    }
    assert "revenue_scope" in contract["rules"]


def test_metric_contracts_are_versioned_and_distinct():
    contracts = metric_contract_records()
    assert {row["name"] for row in contracts} == {
        "paid_conversion_from_first_open",
        "paid_conversion_from_trial_start",
    }
    assert all(row["version"] for row in contracts)
    assert len({row["denominator"] for row in contracts}) == 2
