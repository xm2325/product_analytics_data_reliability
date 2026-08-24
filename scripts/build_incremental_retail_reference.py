from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path
from time import perf_counter

import duckdb
import pandas as pd

from product_analytics.incremental_retail import (
    SimulatedInterruption,
    assert_daily_parity,
    corrupt_metric_partition,
    materialise_incremental_daily,
    normalise_full_daily,
    output_hashes,
    run_incremental,
    state_partition_frame,
    verify_source_manifest,
    write_canonical_partitions,
)
from product_analytics.real_retail import (
    UCI_ONLINE_RETAIL_II_URL,
    build_daily_metrics,
    download_source,
    extract_workbook,
    load_workbook,
    quality_report,
    write_json,
)
from product_analytics.real_source_contract import (
    assert_official_source_archive,
    assert_official_workbook,
)


def _timed(callable_):
    started = perf_counter()
    value = callable_()
    return value, perf_counter() - started


def _full_parquet_rebuild(source_dir: Path, manifest: pd.DataFrame) -> pd.DataFrame:
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
    full = pd.DataFrame({"date": pd.date_range(daily["date"].min(), daily["date"].max(), freq="D")})
    daily = full.merge(daily, on="date", how="left").fillna(0)
    daily["date"] = daily["date"].dt.date
    return normalise_full_daily(daily)


def _fresh_dir(path: Path) -> Path:
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)
    return path


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build v0.37 incremental, recovery and performance evidence on UCI Online Retail II"
    )
    parser.add_argument("--output-dir", type=Path, default=Path("build/incremental-retail"))
    parser.add_argument("--source-archive", type=Path, default=None)
    args = parser.parse_args()

    output_dir = _fresh_dir(args.output_dir)
    source_work_dir = output_dir / "_source"
    source_work_dir.mkdir(parents=True, exist_ok=True)
    archive_path = args.source_archive or source_work_dir / "online_retail_ii.zip"
    if args.source_archive is None:
        download_source(archive_path)
    assert_official_source_archive(archive_path)
    workbook_path = extract_workbook(archive_path, source_work_dir / "extracted")
    assert_official_workbook(workbook_path)

    (canonical_and_sheets, source_ingest_seconds) = _timed(lambda: load_workbook(workbook_path))
    canonical, sheets = canonical_and_sheets
    quality = quality_report(canonical, sheets)

    (full_daily, pandas_full_metric_seconds) = _timed(lambda: build_daily_metrics(canonical))
    full_daily = normalise_full_daily(full_daily)

    source_partition_dir = output_dir / "canonical_partitions"
    (source_manifest, canonical_partition_write_seconds) = _timed(
        lambda: write_canonical_partitions(canonical, source_partition_dir)
    )
    source_manifest.to_csv(output_dir / "incremental_source_partition_manifest.csv", index=False)

    (_, integrity_audit_seconds) = _timed(
        lambda: verify_source_manifest(source_partition_dir, source_manifest)
    )

    (full_parquet_daily, parquet_full_rebuild_seconds) = _timed(
        lambda: _full_parquet_rebuild(source_partition_dir, source_manifest)
    )
    assert_daily_parity(full_daily, full_parquet_daily)

    metric_dir = output_dir / "metric_partitions"
    state_path = output_dir / "incremental_state.json"
    first_stats = run_incremental(source_partition_dir, source_manifest, metric_dir, state_path)
    incremental_daily = materialise_incremental_daily(metric_dir)
    assert_daily_parity(full_daily, incremental_daily)
    baseline_output_hashes = output_hashes(metric_dir)

    noop_stats = run_incremental(source_partition_dir, source_manifest, metric_dir, state_path)
    if noop_stats.processed_partitions != 0 or noop_stats.rows_scanned != 0:
        raise AssertionError("Idempotent replay unexpectedly rescanned source rows")
    if output_hashes(metric_dir) != baseline_output_hashes:
        raise AssertionError("Idempotent replay changed materialised partition hashes")

    recovery_metric_dir = output_dir / "recovery_metric_partitions"
    recovery_state_path = output_dir / "recovery_state.json"
    try:
        run_incremental(
            source_partition_dir,
            source_manifest,
            recovery_metric_dir,
            recovery_state_path,
            stop_after_processed=7,
        )
    except SimulatedInterruption:
        pass
    else:
        raise AssertionError("Expected simulated interruption did not occur")

    partial_state = state_partition_frame(recovery_state_path)
    if len(partial_state) != 7:
        raise AssertionError(f"Expected 7 durable completed partitions, found {len(partial_state)}")
    rows_completed_before_restart = int(partial_state["source_rows"].sum())
    recovery_resume_stats = run_incremental(
        source_partition_dir,
        source_manifest,
        recovery_metric_dir,
        recovery_state_path,
    )
    recovered_daily = materialise_incremental_daily(recovery_metric_dir)
    assert_daily_parity(full_daily, recovered_daily)
    if output_hashes(recovery_metric_dir) != baseline_output_hashes:
        raise AssertionError("Recovered materialisation differs from uninterrupted materialisation")
    if recovery_resume_stats.skipped_partitions < 7:
        raise AssertionError("Restart did not reuse all durable pre-interruption partitions")

    chronological = source_manifest.sort_values("partition_key").reset_index(drop=True)
    repair_row = chronological.iloc[len(chronological) // 2]
    repair_key = str(repair_row["partition_key"])
    repair_rows = int(repair_row["rows"])
    corrupt_metric_partition(metric_dir, state_path, repair_key)
    repair_stats = run_incremental(source_partition_dir, source_manifest, metric_dir, state_path)
    if repair_stats.processed_partitions != 1 or repair_stats.rows_scanned != repair_rows:
        raise AssertionError(
            f"Targeted repair scanned {repair_stats.rows_scanned} rows across "
            f"{repair_stats.processed_partitions} partitions; expected only {repair_key} ({repair_rows})"
        )
    if output_hashes(metric_dir) != baseline_output_hashes:
        raise AssertionError("Targeted repair did not restore the exact pre-corruption output hashes")
    assert_daily_parity(full_daily, materialise_incremental_daily(metric_dir))

    audit_stats = run_incremental(
        source_partition_dir,
        source_manifest,
        metric_dir,
        state_path,
        verify_source_hashes=True,
    )
    if audit_stats.processed_partitions != 0 or audit_stats.rows_scanned != 0:
        raise AssertionError("Integrity audit should not rebuild valid metric partitions")
    if audit_stats.source_hashes_computed != len(source_manifest):
        raise AssertionError("Integrity audit did not hash every source partition")

    source_rows = int(quality["source_rows"])
    partition_count = int(len(source_manifest))
    full_partition_bytes = int(source_manifest["bytes"].sum())
    repeated_full_scan_rows = source_rows
    noop_scan_reduction = 1.0 - noop_stats.rows_scanned / repeated_full_scan_rows
    repair_scan_reduction = 1.0 - repair_stats.rows_scanned / repeated_full_scan_rows
    restart_scan_reduction = rows_completed_before_restart / source_rows

    performance = {
        "version": "0.37.0",
        "dataset": "UCI Online Retail II",
        "source_rows": source_rows,
        "partition_count": partition_count,
        "canonical_partition_bytes": full_partition_bytes,
        "timings_seconds_diagnostic_only": {
            "xlsx_parse_and_normalise": source_ingest_seconds,
            "legacy_pandas_full_metric_build": pandas_full_metric_seconds,
            "one_time_canonical_partition_write": canonical_partition_write_seconds,
            "full_parquet_metric_rebuild": parquet_full_rebuild_seconds,
            "full_source_integrity_audit": integrity_audit_seconds,
            "initial_incremental_materialisation": first_stats.elapsed_seconds,
            "idempotent_noop_replay": noop_stats.elapsed_seconds,
            "targeted_single_partition_repair": repair_stats.elapsed_seconds,
        },
        "deterministic_work_reduction": {
            "full_rebuild_rows_scanned": repeated_full_scan_rows,
            "idempotent_noop_rows_scanned": noop_stats.rows_scanned,
            "idempotent_noop_scan_reduction_fraction": noop_scan_reduction,
            "idempotent_noop_large_source_hashes_computed": noop_stats.source_hashes_computed,
            "targeted_repair_partition": repair_key,
            "targeted_repair_rows_scanned": repair_stats.rows_scanned,
            "targeted_repair_scan_reduction_fraction": repair_scan_reduction,
            "durable_rows_reused_after_interruption": rows_completed_before_restart,
            "restart_scan_reduction_fraction": restart_scan_reduction,
            "restart_rows_scanned": recovery_resume_stats.rows_scanned,
            "restart_partitions_skipped": recovery_resume_stats.skipped_partitions,
        },
        "performance_interpretation": {
            "one_time_bottleneck": "XLSX decompression/XML parsing and canonical type normalisation remain source-ingestion work; v0.37 does not claim to eliminate that first-load cost.",
            "repeated_work_bottleneck": "v0.36 rebuilt daily metrics from the full external snapshot; v0.37 persists immutable month partitions and processes only missing, revised or invalidated partitions.",
            "normal_noop_policy": "trust pinned canonical manifest SHA values, stat large source files, and hash only compact derived outputs; no source rows are SQL-scanned and no large source partitions are re-hashed.",
            "integrity_policy": "full source SHA verification remains available as an explicit audit rather than being charged to every no-op run.",
            "wall_clock_boundary": "runner timings are diagnostic and are not pass/fail gates because shared-runner load is variable; deterministic row/partition work reduction is the performance contract.",
        },
    }

    recovery = {
        "version": "0.37.0",
        "partition_count": partition_count,
        "interruption_after_completed_partitions": 7,
        "durable_rows_completed_before_restart": rows_completed_before_restart,
        "resume_partitions_skipped": recovery_resume_stats.skipped_partitions,
        "resume_partitions_processed": recovery_resume_stats.processed_partitions,
        "resume_rows_scanned": recovery_resume_stats.rows_scanned,
        "recovered_equals_uninterrupted": True,
        "idempotent_noop_processed_partitions": noop_stats.processed_partitions,
        "idempotent_noop_rows_scanned": noop_stats.rows_scanned,
        "idempotent_output_hashes_unchanged": True,
        "targeted_repair_partition": repair_key,
        "targeted_repair_rows_scanned": repair_stats.rows_scanned,
        "targeted_repair_processed_partitions": repair_stats.processed_partitions,
        "targeted_repair_restored_exact_output_hashes": True,
        "full_source_integrity_audit_hashes": audit_stats.source_hashes_computed,
    }

    contract = {
        "version": "0.37.0",
        "source": "UCI Online Retail II",
        "source_url": UCI_ONLINE_RETAIL_II_URL,
        "partition_key": "calendar month derived from InvoiceDate/event time",
        "partition_semantics": "historical replay partitioning only; InvoiceDate is not claimed to be ingestion time",
        "canonical_store": "immutable month-partitioned Parquet plus SHA-256 manifest",
        "state_commit_rule": "write durable state after every successfully materialised partition",
        "reuse_rule": "reuse only when manifest source SHA/row count and compact materialised-output SHA agree with durable state",
        "repair_rule": "rebuild only missing, source-revised or output-invalidated partitions",
        "idempotency_rule": "a repeated run against unchanged source/state must process zero partitions and scan zero source rows",
        "parity_rule": "incremental, interrupted/resumed and targeted-repaired daily outputs must exactly equal a clean full rebuild after the declared six-decimal revenue normalisation",
        "performance_gate": "deterministic rows/partitions scanned; wall-clock timings are diagnostic only",
        "source_integrity_rule": "normal runs trust the pinned canonical manifest; explicit integrity audit hashes every source partition",
        "no_ingestion_time_claim": True,
    }

    full_daily.to_csv(output_dir / "incremental_full_rebuild_daily.csv", index=False)
    incremental_daily.to_csv(output_dir / "incremental_daily_metrics.csv", index=False)
    state_partition_frame(state_path).to_csv(output_dir / "incremental_materialisation_manifest.csv", index=False)
    write_json(output_dir / "incremental_contract.json", contract)
    write_json(output_dir / "incremental_recovery_evidence.json", recovery)
    write_json(output_dir / "incremental_performance.json", performance)

    summary = {
        "version": "0.37.0",
        "source_rows": source_rows,
        "partition_count": partition_count,
        "full_incremental_exact_parity": True,
        "idempotent_noop_rows_scanned": noop_stats.rows_scanned,
        "interrupted_resume_exact_parity": True,
        "targeted_repair_partition": repair_key,
        "targeted_repair_rows_scanned": repair_stats.rows_scanned,
        "targeted_repair_scan_reduction_fraction": repair_scan_reduction,
        "full_integrity_audit_source_hashes": audit_stats.source_hashes_computed,
    }
    write_json(output_dir / "incremental_summary.json", summary)

    print(json.dumps(summary, indent=2, sort_keys=True))
    print(json.dumps(performance, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
