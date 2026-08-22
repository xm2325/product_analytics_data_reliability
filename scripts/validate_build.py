from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from product_analytics.config import PRODUCTS
from product_analytics.provenance import validate_manifest


EXPECTED_PORTABLE_ARTIFACTS = {
    "bronze_events.csv", "rejected_events.csv", "silver_events.csv", "gold_daily_metrics.csv",
    "revenue_reconciliation.csv", "product_config.csv", "forecast_evaluations.csv",
    "dau_definition_migration.csv", "dau_definition_migration_summary.csv",
    "retention_maturity_ledger.csv", "retention_maturity_summary.csv",
    "activity_retention_cohorts.csv", "activity_retention_summary.csv",
    "late_arrival_summary.csv", "watermark_late_events.csv",
    "watermark_metric_revisions.csv", "watermark_revision_summary.csv",
    "quality_report.json", "metric_contracts.json", "retention_contracts.json",
    "event_contract.json", "late_arrival_contract.json", "reference_summary.json", "MANIFEST.json",
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
    if quality.get("invalid_ingestion_timestamp_rows") != 0:
        failures.append("generated_invalid_ingestion_timestamp")
    if quality.get("ingestion_before_event_rows") != 0:
        failures.append("generated_ingestion_before_event")

    rejected = pd.read_csv(root / "rejected_events.csv")
    if len(rejected) != quality["rows_rejected"]:
        failures.append("rejected_row_count")
    if "reject_reason" not in rejected.columns or rejected["reject_reason"].fillna("").eq("").any():
        failures.append("reject_reason_missing")

    silver = pd.read_csv(root / "silver_events.csv")
    if "app_open" not in set(silver["event_type"]):
        failures.append("no_app_open_activity")
    if "ingested_at" not in silver.columns:
        failures.append("missing_processing_time")
    else:
        event_ts = pd.to_datetime(silver["event_ts"], utc=True, errors="coerce")
        ingested_at = pd.to_datetime(silver["ingested_at"], utc=True, errors="coerce")
        if event_ts.isna().any() or ingested_at.isna().any():
            failures.append("unparseable_certified_processing_time")
        elif ingested_at.lt(event_ts).any():
            failures.append("certified_processing_time_before_event")

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
        "daily_active_users", "daily_active_users_legacy_any_event",
        "paid_conversion_from_first_open", "paid_conversion_from_trial_start",
    }
    if names != required_contracts:
        failures.append("metric_contract_set")
    contract_by_name = {row["name"]: row for row in contracts}
    if contract_by_name.get("daily_active_users", {}).get("version") != "2.0":
        failures.append("dau_v2_contract_version")
    if "deprecated" not in contract_by_name.get("daily_active_users_legacy_any_event", {}).get("version", ""):
        failures.append("dau_v1_not_deprecated")

    retention_contracts = json.loads((root / "retention_contracts.json").read_text(encoding="utf-8"))
    retention_contract_by_name = {row["name"]: row for row in retention_contracts}
    if set(retention_contract_by_name) != {"d7_activity_retention", "d30_activity_retention"}:
        failures.append("retention_contract_set")
    if {row["horizon_days"] for row in retention_contracts} != {7, 30}:
        failures.append("retention_contract_horizons")
    if any(row["return_window"] != "exact_calendar_day" for row in retention_contracts):
        failures.append("retention_contract_window")

    event = json.loads((root / "event_contract.json").read_text(encoding="utf-8"))
    if set(event["allowed_products"]) != expected_products:
        failures.append("event_contract_products")
    required_event_types = {"first_open", "app_open", "trial_start", "paid_subscription", "purchase"}
    if set(event["allowed_event_types"]) != required_event_types:
        failures.append("event_contract_event_types")
    if event.get("activity_event") != "app_open":
        failures.append("event_contract_activity_event")
    if event.get("generated_processing_time_column") != "ingested_at":
        failures.append("event_contract_processing_time")

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

    maturity = pd.read_csv(root / "retention_maturity_ledger.csv")
    if set(maturity["product"]) != expected_products or set(maturity["horizon_days"]) != {7, 30}:
        failures.append("maturity_product_or_horizon_set")
    maturity["mature"] = maturity["mature"].astype(str).str.lower().eq("true")
    mature = maturity.loc[maturity["mature"]].copy()
    immature = maturity.loc[~maturity["mature"]].copy()
    if mature.empty or immature.empty:
        failures.append("maturity_states_not_both_present")
    if not (mature["eligible_users"] == mature["cohort_users"]).all() or not (mature["excluded_users"] == 0).all():
        failures.append("mature_denominator_accounting")
    if mature["retained_users"].isna().any() or not mature["retention_rate"].between(0, 1).all():
        failures.append("mature_retention_missing_or_invalid")
    if not (immature["eligible_users"] == 0).all() or not (immature["excluded_users"] == immature["cohort_users"]).all():
        failures.append("immature_denominator_accounting")
    if immature["retained_users"].notna().any() or immature["retention_rate"].notna().any():
        failures.append("immature_future_outcomes_leaked")
    if not immature["exclusion_reason"].eq("target_date_after_analysis_as_of").all():
        failures.append("immature_exclusion_reason")
    mature_target = pd.to_datetime(mature["target_date"])
    mature_as_of = pd.to_datetime(mature["analysis_as_of"])
    immature_target = pd.to_datetime(immature["target_date"])
    immature_as_of = pd.to_datetime(immature["analysis_as_of"])
    if not mature_target.le(mature_as_of).all() or not immature_target.gt(immature_as_of).all():
        failures.append("maturity_date_boundary")

    maturity_summary = pd.read_csv(root / "retention_maturity_summary.csv")
    if set(maturity_summary["product"]) != expected_products or len(maturity_summary) != len(PRODUCTS) * 2:
        failures.append("maturity_summary_product_set")
    if not (maturity_summary["mature_cohorts"] + maturity_summary["immature_cohorts"] == maturity_summary["cohorts"]).all():
        failures.append("maturity_cohort_accounting")
    if not (maturity_summary["eligible_users"] + maturity_summary["excluded_users"] == maturity_summary["cohort_users"]).all():
        failures.append("maturity_user_accounting")
    maturity_pivot = maturity_summary.pivot(index="product", columns="horizon_days", values="eligible_user_fraction")
    if not (maturity_pivot[30] < maturity_pivot[7]).all():
        failures.append("longer_horizon_not_less_mature")

    retention_cohorts = pd.read_csv(root / "activity_retention_cohorts.csv")
    if len(retention_cohorts) != len(mature):
        failures.append("retention_cohorts_not_mature_subset")
    retention = pd.read_csv(root / "activity_retention_summary.csv")
    if set(retention["product"]) != expected_products or set(retention["horizon_days"]) != {7, 30}:
        failures.append("retention_product_or_horizon_set")
    if not retention["retention_rate"].between(0, 1).all():
        failures.append("retention_rate_bounds")
    pivot = retention.pivot(index="product", columns="horizon_days", values="retention_rate")
    if not (pivot[30] < pivot[7]).all():
        failures.append("retention_decay_not_visible")

    # v0.26 processing-time and watermark evidence.
    arrival = pd.read_csv(root / "late_arrival_summary.csv")
    if set(arrival["product"]) != expected_products:
        failures.append("late_arrival_product_set")
    if int(arrival["events"].sum()) != len(silver):
        failures.append("late_arrival_row_accounting")
    if int(arrival["late_beyond_watermark"].sum()) <= 0:
        failures.append("no_controlled_late_arrivals")
    if not arrival["late_fraction"].between(0, 1).all():
        failures.append("late_fraction_bounds")
    if arrival["delay_max_hours"].max() <= 48.0:
        failures.append("late_tail_missing")

    late_contract = json.loads((root / "late_arrival_contract.json").read_text(encoding="utf-8"))
    if float(late_contract.get("allowed_lateness_hours", -1)) != 48.0:
        failures.append("watermark_contract_hours")
    if late_contract.get("event_time_field") != "event_ts" or late_contract.get("processing_time_field") != "ingested_at":
        failures.append("watermark_contract_fields")

    late_events = pd.read_csv(root / "watermark_late_events.csv")
    if late_events.empty:
        failures.append("no_late_events_missing_from_finalized_snapshot")
    else:
        event_date = pd.to_datetime(late_events["event_date"])
        watermark_date = pd.to_datetime(late_events["watermark_event_date"])
        ingested = pd.to_datetime(late_events["ingested_at"], utc=True)
        processing_as_of = pd.to_datetime(late_events["processing_as_of"], utc=True)
        if not event_date.le(watermark_date).all():
            failures.append("late_event_after_watermark_date")
        if not ingested.gt(processing_as_of).all():
            failures.append("late_event_was_already_available")
        if late_events["event_id"].duplicated().any():
            failures.append("late_event_duplicate_id")

    revisions = pd.read_csv(root / "watermark_metric_revisions.csv")
    if set(revisions["product"]) != expected_products or set(revisions["metric"]) != {"dau", "revenue_gbp", "paid_subscription"}:
        failures.append("revision_product_or_metric_set")
    if (revisions["revision"] < -1e-12).any():
        failures.append("late_arrival_negative_revision")
    changed = revisions["changed_after_watermark"].astype(str).str.lower().eq("true")
    if not changed.any():
        failures.append("watermark_never_revises_metric")

    revision_summary = pd.read_csv(root / "watermark_revision_summary.csv")
    if len(revision_summary) != len(PRODUCTS) * 3:
        failures.append("revision_summary_row_count")
    if revision_summary["revised_dates"].sum() <= 0:
        failures.append("revision_summary_no_changed_dates")

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
