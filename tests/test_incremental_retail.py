from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from product_analytics.incremental_retail import (
    SimulatedInterruption,
    assert_daily_parity,
    corrupt_metric_partition,
    materialise_incremental_daily,
    output_hashes,
    run_incremental,
    state_partition_frame,
    verify_source_manifest,
    write_canonical_partitions,
)
from product_analytics.real_retail import build_daily_metrics


def _canonical() -> pd.DataFrame:
    frame = pd.DataFrame(
        {
            "source_row_id": range(6),
            "invoice_no": ["A1", "A1", "A2", "B1", "B2", "B3"],
            "stock_code": ["x", "y", "x", "z", "x", "q"],
            "description": ["x", "y", "x", "z", "x", "q"],
            "quantity": [1, 2, 1, 3, 1, 2],
            "invoice_ts": pd.to_datetime(
                [
                    "2011-01-02 10:00",
                    "2011-01-02 10:01",
                    "2011-01-03 09:00",
                    "2011-02-01 12:00",
                    "2011-02-02 12:00",
                    "2011-02-02 13:00",
                ]
            ),
            "unit_price_gbp": [2.0, 1.5, 4.0, 2.0, 5.0, 3.0],
            "customer_id": pd.Series(["1", "1", pd.NA, "2", "3", "3"], dtype="string"),
            "country": ["UK"] * 6,
            "source_sheet": ["toy"] * 6,
            "is_cancellation": [False] * 6,
        }
    )
    frame["line_value_gbp"] = frame["quantity"] * frame["unit_price_gbp"]
    frame["is_purchase_line"] = True
    frame["is_identified_purchase_line"] = frame["customer_id"].notna()
    return frame


def test_incremental_matches_full_and_noop_scans_zero_rows(tmp_path: Path) -> None:
    canonical = _canonical()
    source_dir = tmp_path / "source"
    metric_dir = tmp_path / "metrics"
    state = tmp_path / "state.json"
    manifest = write_canonical_partitions(canonical, source_dir)
    verify_source_manifest(source_dir, manifest)

    first = run_incremental(source_dir, manifest, metric_dir, state)
    assert first.processed_partitions == 2
    assert first.rows_scanned == len(canonical)
    assert_daily_parity(build_daily_metrics(canonical), materialise_incremental_daily(metric_dir))

    hashes = output_hashes(metric_dir)
    second = run_incremental(source_dir, manifest, metric_dir, state)
    assert second.processed_partitions == 0
    assert second.skipped_partitions == 2
    assert second.rows_scanned == 0
    assert second.source_hashes_computed == 0
    assert output_hashes(metric_dir) == hashes


def test_interrupted_run_resumes_without_replaying_durable_partition(tmp_path: Path) -> None:
    canonical = _canonical()
    source_dir = tmp_path / "source"
    metric_dir = tmp_path / "metrics"
    state = tmp_path / "state.json"
    manifest = write_canonical_partitions(canonical, source_dir)

    with pytest.raises(SimulatedInterruption):
        run_incremental(source_dir, manifest, metric_dir, state, stop_after_processed=1)
    partial = state_partition_frame(state)
    assert len(partial) == 1
    durable_rows = int(partial["source_rows"].sum())

    resumed = run_incremental(source_dir, manifest, metric_dir, state)
    assert resumed.skipped_partitions == 1
    assert resumed.processed_partitions == 1
    assert resumed.rows_scanned == len(canonical) - durable_rows
    assert_daily_parity(build_daily_metrics(canonical), materialise_incremental_daily(metric_dir))


def test_corrupt_materialisation_repairs_only_affected_partition(tmp_path: Path) -> None:
    canonical = _canonical()
    source_dir = tmp_path / "source"
    metric_dir = tmp_path / "metrics"
    state = tmp_path / "state.json"
    manifest = write_canonical_partitions(canonical, source_dir)
    run_incremental(source_dir, manifest, metric_dir, state)
    expected_hashes = output_hashes(metric_dir)

    repair_key = "2011-02"
    repair_rows = int(manifest.loc[manifest["partition_key"] == repair_key, "rows"].iloc[0])
    corrupt_metric_partition(metric_dir, state, repair_key)
    repaired = run_incremental(source_dir, manifest, metric_dir, state)

    assert repaired.processed_partitions == 1
    assert repaired.skipped_partitions == 1
    assert repaired.rows_scanned == repair_rows
    assert output_hashes(metric_dir) == expected_hashes


def test_source_revision_manifest_invalidates_only_changed_month(tmp_path: Path) -> None:
    canonical = _canonical()
    source_dir = tmp_path / "source"
    metric_dir = tmp_path / "metrics"
    state = tmp_path / "state.json"
    original_manifest = write_canonical_partitions(canonical, source_dir)
    run_incremental(source_dir, original_manifest, metric_dir, state)

    revised = canonical.copy()
    revised.loc[revised["source_row_id"] == 3, "quantity"] = 4
    revised.loc[revised["source_row_id"] == 3, "line_value_gbp"] = 8.0
    revised_manifest = write_canonical_partitions(revised, source_dir)
    changed = run_incremental(source_dir, revised_manifest, metric_dir, state)

    feb_rows = int(revised_manifest.loc[revised_manifest["partition_key"] == "2011-02", "rows"].iloc[0])
    assert changed.processed_partitions == 1
    assert changed.skipped_partitions == 1
    assert changed.rows_scanned == feb_rows
    assert_daily_parity(build_daily_metrics(revised), materialise_incremental_daily(metric_dir))

    restored_manifest = write_canonical_partitions(canonical, source_dir)
    restored = run_incremental(source_dir, restored_manifest, metric_dir, state)
    assert restored.processed_partitions == 1
    assert restored.rows_scanned == feb_rows
    assert_daily_parity(build_daily_metrics(canonical), materialise_incremental_daily(metric_dir))
