from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from product_analytics.config import PRODUCTS
from product_analytics.provenance import validate_manifest


EXPECTED_PORTABLE_ARTIFACTS = {
    "bronze_events.csv",
    "rejected_events.csv",
    "silver_events.csv",
    "gold_daily_metrics.csv",
    "revenue_reconciliation.csv",
    "product_config.csv",
    "forecast_evaluations.csv",
    "dau_definition_migration.csv",
    "dau_definition_migration_summary.csv",
    "activity_retention_cohorts.csv",
    "activity_retention_summary.csv",
    "quality_report.json",
    "metric_contracts.json",
    "event_contract.json",
    "reference_summary.json",
    "MANIFEST.json",
}


def validate_build(root: Path) -> list[str]:
    failures: list[str] = []
    missing = sorted(name for name in EXPECTED_PORTABLE_ARTIFACTS if not (root / name).is_file())
    failures.extend(f"missing:{name}" for name in missing)
    if missing:
        return failures

    failures.extend(validate_manifest(root / "MANIFEST.json", root=root))

    expected_products = {p.name for p in PRODUCTS}
    quality = json.loads((root / "quality_report.json").read_text(encoding="utf-8"))
    if quality["rows_raw"] != quality["rows_certified"] + quality["rows_rejected"]:
        failures.append("row_accounting")
    if quality["rows_rejected"] <= 0:
        failures.append("no_controlled_faults_rejected")

    rejected = pd.read_csv(root / "rejected_events.csv")
    if len(rejected) != quality["rows_rejected"]:
        failures.append("rejected_row_count")
    if "reject_reason" not in rejected.columns or rejected["reject_reason"].fillna("").eq("").any():
        failures.append("reject_reason_missing")

    silver = pd.read_csv(root / "silver_events.csv")
    if "app_open" not in set(silver["event_type"]):
        failures.append("no_app_open_activity")

    reconciliation = pd.read_csv(root / "revenue_reconciliation.csv")
    if set(reconciliation["product"]) != expected_products:
        failures.append("reconciliation_product_set")
    if (reconciliation["raw_revenue_gbp"] < reconciliation["certified_revenue_gbp"]).any():
        failures.append("reconciliation_direction")
    if not (reconciliation["overstatement_gbp"] > 0).any():
        failures.append("fault_injection_not_visible_in_revenue")

    forecasts = pd.read_csv(root / "forecast_evaluations.csv")
    if len(forecasts) != len(PRODUCTS) * 3:
        failures.append("forecast_row_count")
    if not set(forecasts["approved"].astype(str).str.lower()).issubset({"true", "false"}):
        failures.append("forecast_approved_not_boolean")

    contracts = json.loads((root / "metric_contracts.json").read_text(encoding="utf-8"))
    names = {row["name"] for row in contracts}
    required_contracts = {
        "daily_active_users",
        "daily_active_users_legacy_any_event",
        "paid_conversion_from_first_open",
        "paid_conversion_from_trial_start",
    }
    if names != required_contracts:
        failures.append("metric_contract_set")
    contract_by_name = {row["name"]: row for row in contracts}
    if contract_by_name.get("daily_active_users", {}).get("version") != "2.0":
        failures.append("dau_v2_contract_version")
    if "deprecated" not in contract_by_name.get("daily_active_users_legacy_any_event", {}).get("version", ""):
        failures.append("dau_v1_not_deprecated")

    event = json.loads((root / "event_contract.json").read_text(encoding="utf-8"))
    if set(event["allowed_products"]) != expected_products:
        failures.append("event_contract_products")
    required_event_types = {"first_open", "app_open", "trial_start", "paid_subscription", "purchase"}
    if set(event["allowed_event_types"]) != required_event_types:
        failures.append("event_contract_event_types")
    if event.get("activity_event") != "app_open":
        failures.append("event_contract_activity_event")

    migration = pd.read_csv(root / "dau_definition_migration.csv")
    if set(migration["product"]) != expected_products:
        failures.append("migration_product_set")
    if (migration["dau_legacy_any_event"] < migration["dau"]).any():
        failures.append("legacy_dau_below_app_open_dau")
    if not (migration["delta_users"] > 0).any():
        failures.append("dau_definitions_never_differ")

    migration_summary = pd.read_csv(root / "dau_definition_migration_summary.csv")
    if set(migration_summary["product"]) != expected_products or len(migration_summary) != len(PRODUCTS):
        failures.append("migration_summary_product_set")
    if (migration_summary["mean_dau_v2"] <= 0).any():
        failures.append("nonpositive_dau_v2")

    retention = pd.read_csv(root / "activity_retention_summary.csv")
    if set(retention["product"]) != expected_products:
        failures.append("retention_product_set")
    if set(retention["horizon_days"]) != {7, 30} or len(retention) != len(PRODUCTS) * 2:
        failures.append("retention_horizon_set")
    if not retention["retention_rate"].between(0, 1).all():
        failures.append("retention_rate_bounds")
    pivot = retention.pivot(index="product", columns="horizon_days", values="retention_rate")
    if not (pivot[30] < pivot[7]).all():
        failures.append("retention_decay_not_visible")

    config = pd.read_csv(root / "product_config.csv")
    if set(config["name"]) != expected_products:
        failures.append("product_config_set")
    if (config["activity_horizon_days"] < 30).any():
        failures.append("activity_horizon_too_short")

    return failures


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate a generated reference build")
    parser.add_argument("root", nargs="?", default="build/reference")
    args = parser.parse_args()
    root = Path(args.root)
    failures = validate_build(root)
    if failures:
        raise SystemExit("Build validation failed: " + ", ".join(failures))
    print(f"Build validation passed: {root}")


if __name__ == "__main__":
    main()
