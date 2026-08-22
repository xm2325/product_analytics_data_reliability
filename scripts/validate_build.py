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
    "forecast_evaluations.csv",
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

    reconciliation = pd.read_csv(root / "revenue_reconciliation.csv")
    expected_products = {p.name for p in PRODUCTS}
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
    required_contracts = {"paid_conversion_from_first_open", "paid_conversion_from_trial_start"}
    if names != required_contracts:
        failures.append("metric_contract_set")

    event = json.loads((root / "event_contract.json").read_text(encoding="utf-8"))
    if set(event["allowed_products"]) != expected_products:
        failures.append("event_contract_products")
    required_event_types = {"first_open", "trial_start", "paid_subscription", "purchase"}
    if set(event["allowed_event_types"]) != required_event_types:
        failures.append("event_contract_event_types")

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
