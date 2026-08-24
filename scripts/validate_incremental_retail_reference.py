from __future__ import annotations

import argparse
import json
from pathlib import Path

import duckdb
import pandas as pd

from product_analytics.incremental_retail import (
    assert_daily_parity,
    normalise_full_daily,
    sha256_file,
    verify_source_manifest,
)


def _independent_full_rebuild(source_dir: Path, manifest: pd.DataFrame) -> pd.DataFrame:
    paths = [str(source_dir / path) for path in manifest.sort_values("partition_key")["path"]]
    con = duckdb.connect()
    try:
        daily = con.execute(
            """
            SELECT
                CAST(invoice_ts AS DATE) AS date,
                ROUND(SUM(CASE WHEN is_purchase_line THEN line_value_gbp ELSE 0 END), 6) AS revenue_gbp,
                COUNT(DISTINCT CASE WHEN is_purchase_line THEN invoice_no END) AS orders,
                COALESCE(SUM(CASE WHEN is_purchase_line THEN quantity ELSE 0 END), 0) AS units,
                SUM(CASE WHEN is_purchase_line THEN 1 ELSE 0 END) AS purchase_lines,
                COUNT(DISTINCT CASE
                    WHEN is_purchase_line AND customer_id IS NOT NULL THEN customer_id
                END) AS active_customers
            FROM read_parquet(?)
            WHERE invoice_ts IS NOT NULL
            GROUP BY 1
            ORDER BY 1
            """,
            [paths],
        ).df()
    finally:
        con.close()
    daily["date"] = pd.to_datetime(daily["date"])
    full_calendar = pd.DataFrame(
        {"date": pd.date_range(daily["date"].min(), daily["date"].max(), freq="D")}
    )
    daily = full_calendar.merge(daily, on="date", how="left").fillna(0)
    daily["date"] = daily["date"].dt.date
    return normalise_full_daily(daily)


def main() -> None:
    parser = argparse.ArgumentParser(description="Independently validate v0.37 incremental retail evidence")
    parser.add_argument("output_dir", type=Path)
    args = parser.parse_args()
    root = args.output_dir

    required = [
        "incremental_source_partition_manifest.csv",
        "incremental_materialisation_manifest.csv",
        "incremental_full_rebuild_daily.csv",
        "incremental_daily_metrics.csv",
        "incremental_contract.json",
        "incremental_recovery_evidence.json",
        "incremental_performance.json",
        "incremental_summary.json",
    ]
    missing = [name for name in required if not (root / name).exists()]
    if missing:
        raise AssertionError(f"Missing v0.37 evidence files: {missing}")

    source_manifest = pd.read_csv(root / "incremental_source_partition_manifest.csv")
    materialisation_manifest = pd.read_csv(root / "incremental_materialisation_manifest.csv")
    contract = json.loads((root / "incremental_contract.json").read_text(encoding="utf-8"))
    recovery = json.loads((root / "incremental_recovery_evidence.json").read_text(encoding="utf-8"))
    performance = json.loads((root / "incremental_performance.json").read_text(encoding="utf-8"))
    summary = json.loads((root / "incremental_summary.json").read_text(encoding="utf-8"))

    if contract["version"] != "0.37.0" or summary["version"] != "0.37.0":
        raise AssertionError("Unexpected v0.37 evidence version")
    if contract["no_ingestion_time_claim"] is not True:
        raise AssertionError("Real source must not be represented as having ingestion-time evidence")

    source_dir = root / "canonical_partitions"
    verify_source_manifest(source_dir, source_manifest)

    if int(source_manifest["rows"].sum()) != 1_067_371:
        raise AssertionError("Canonical partition rows do not reconcile to the pinned UCI source")
    if source_manifest["partition_key"].duplicated().any():
        raise AssertionError("Duplicate source partition keys")
    if len(materialisation_manifest) != len(source_manifest):
        raise AssertionError("Materialised partition count does not match canonical source partition count")
    if set(materialisation_manifest["status"]) != {"complete"}:
        raise AssertionError("Not every materialised partition is complete")

    for row in materialisation_manifest.to_dict("records"):
        metric_path = root / "metric_partitions" / str(row["metric_path"])
        if not metric_path.exists():
            raise AssertionError(f"Missing materialised metric partition: {metric_path.name}")
        if sha256_file(metric_path) != str(row["metric_sha256"]):
            raise AssertionError(f"Materialised metric partition SHA mismatch: {metric_path.name}")

    generated_incremental = pd.read_csv(root / "incremental_daily_metrics.csv")
    generated_full = pd.read_csv(root / "incremental_full_rebuild_daily.csv")
    independent_full = _independent_full_rebuild(source_dir, source_manifest)
    assert_daily_parity(generated_full, generated_incremental)
    assert_daily_parity(independent_full, generated_incremental)

    if recovery["idempotent_noop_processed_partitions"] != 0:
        raise AssertionError("Idempotent no-op processed a partition")
    if recovery["idempotent_noop_rows_scanned"] != 0:
        raise AssertionError("Idempotent no-op scanned source rows")
    if recovery["idempotent_output_hashes_unchanged"] is not True:
        raise AssertionError("Idempotent replay changed output hashes")
    if recovery["recovered_equals_uninterrupted"] is not True:
        raise AssertionError("Interrupted/resumed output differs from uninterrupted output")
    if recovery["resume_partitions_skipped"] < recovery["interruption_after_completed_partitions"]:
        raise AssertionError("Restart replayed durable pre-interruption partitions")
    if recovery["targeted_repair_processed_partitions"] != 1:
        raise AssertionError("Targeted repair did not isolate work to one partition")
    if recovery["targeted_repair_restored_exact_output_hashes"] is not True:
        raise AssertionError("Targeted repair failed to restore exact output hashes")
    if recovery["full_source_integrity_audit_hashes"] != len(source_manifest):
        raise AssertionError("Explicit integrity audit did not hash all canonical source partitions")

    work = performance["deterministic_work_reduction"]
    source_rows = int(performance["source_rows"])
    if work["full_rebuild_rows_scanned"] != source_rows:
        raise AssertionError("Full-rebuild scan baseline mismatch")
    if work["idempotent_noop_rows_scanned"] != 0:
        raise AssertionError("No-op performance contract regressed")
    if work["idempotent_noop_large_source_hashes_computed"] != 0:
        raise AssertionError("Normal no-op unexpectedly re-hashed large source partitions")
    if abs(work["idempotent_noop_scan_reduction_fraction"] - 1.0) > 1e-12:
        raise AssertionError("No-op scan reduction is not 100%")

    repair_key = str(work["targeted_repair_partition"])
    expected_repair_rows = int(
        source_manifest.loc[source_manifest["partition_key"] == repair_key, "rows"].iloc[0]
    )
    if work["targeted_repair_rows_scanned"] != expected_repair_rows:
        raise AssertionError("Targeted repair scan count does not equal the affected partition")
    expected_reduction = 1.0 - expected_repair_rows / source_rows
    if abs(work["targeted_repair_scan_reduction_fraction"] - expected_reduction) > 1e-12:
        raise AssertionError("Targeted repair scan-reduction claim is inconsistent")
    if work["restart_rows_scanned"] + work["durable_rows_reused_after_interruption"] != source_rows:
        raise AssertionError("Restart work does not reconcile to full source rows")

    timings = performance["timings_seconds_diagnostic_only"]
    if any(float(value) <= 0 for value in timings.values()):
        raise AssertionError("Expected positive diagnostic timings")

    print(
        "Incremental-recovery validation passed: "
        f"{len(source_manifest)} partitions, {source_rows:,} source rows, "
        f"noop scans={work['idempotent_noop_rows_scanned']}, "
        f"targeted repair={repair_key} / {expected_repair_rows:,} rows"
    )


if __name__ == "__main__":
    main()
