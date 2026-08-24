from __future__ import annotations

import argparse
from dataclasses import asdict
from hashlib import sha256
import json
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

from product_analytics.forecasting import ForecastPlanningGate, evaluate_forecast_plan, rolling_origin_seasonal_naive
from product_analytics.real_retail import extract_workbook, load_workbook

EXPECTED_SOURCE_ROWS = 1_067_371
EXPECTED_DATE_MIN_PREFIX = "2009-12-01"
EXPECTED_DATE_MAX_PREFIX = "2011-12-09"


def _hash_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def _assert_close_frame(actual: pd.DataFrame, expected: pd.DataFrame, key: str, numeric: list[str]) -> None:
    left = actual.sort_values(key).reset_index(drop=True)
    right = expected.sort_values(key).reset_index(drop=True)
    if left[key].astype(str).tolist() != right[key].astype(str).tolist():
        raise AssertionError(f"Key mismatch for {key}")
    for column in numeric:
        if not np.allclose(
            pd.to_numeric(left[column], errors="raise"),
            pd.to_numeric(right[column], errors="raise"),
            rtol=1e-10,
            atol=1e-8,
            equal_nan=True,
        ):
            raise AssertionError(f"Numeric mismatch for {column}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Independently validate the v0.36 UCI real-data evidence lane")
    parser.add_argument("output_dir", type=Path)
    args = parser.parse_args()
    output_dir = args.output_dir

    required = [
        "real_daily_metrics.csv",
        "real_semantic_comparison.csv",
        "real_forecast_backtest.csv",
        "real_forecast_evaluations.csv",
        "real_source_provenance.json",
        "real_quality_report.json",
        "real_metric_contract.json",
        "real_data_summary.json",
        "real_manifest.json",
    ]
    missing = [name for name in required if not (output_dir / name).exists()]
    if missing:
        raise AssertionError(f"Missing real-data evidence: {missing}")

    provenance = _load_json(output_dir / "real_source_provenance.json")
    quality = _load_json(output_dir / "real_quality_report.json")
    summary = _load_json(output_dir / "real_data_summary.json")
    contract = _load_json(output_dir / "real_metric_contract.json")
    manifest = _load_json(output_dir / "real_manifest.json")

    if provenance["doi"] != "10.24432/C5CG6D" or provenance["license"] != "CC BY 4.0":
        raise AssertionError("Unexpected UCI provenance metadata")
    if provenance["ingestion_timestamp_available"] is not False or provenance["late_arrival_or_watermark_claimed"] is not False:
        raise AssertionError("Real-data lane must not claim processing-time evidence absent from the source")
    if contract["ingestion_timestamp_available"] is not False:
        raise AssertionError("Metric contract incorrectly claims an ingestion timestamp")
    if int(quality["source_rows"]) != EXPECTED_SOURCE_ROWS:
        raise AssertionError(f"Expected {EXPECTED_SOURCE_ROWS} UCI rows, got {quality['source_rows']}")
    if not str(quality["date_min"]).startswith(EXPECTED_DATE_MIN_PREFIX):
        raise AssertionError(f"Unexpected source start date: {quality['date_min']}")
    if not str(quality["date_max"]).startswith(EXPECTED_DATE_MAX_PREFIX):
        raise AssertionError(f"Unexpected source end date: {quality['date_max']}")

    archive_path = output_dir / "_source" / "online_retail_ii.zip"
    if not archive_path.exists():
        raise AssertionError("Cached source archive missing from build workspace")
    if _hash_file(archive_path) != provenance["archive_sha256"]:
        raise AssertionError("Source archive SHA-256 does not match provenance")

    validate_extract_dir = output_dir / "_validate_source"
    workbook_path = extract_workbook(archive_path, validate_extract_dir)
    if _hash_file(workbook_path) != provenance["workbook_sha256"]:
        raise AssertionError("Extracted workbook SHA-256 does not match provenance")
    canonical, sheets = load_workbook(workbook_path)
    if len(canonical) != EXPECTED_SOURCE_ROWS:
        raise AssertionError("Independent source reload row count mismatch")
    if sheets != provenance["sheets"]:
        raise AssertionError("Workbook sheet inventory mismatch")

    con = duckdb.connect()
    con.register("source_lines", canonical)
    independent_quality = con.execute(
        """
        SELECT
          COUNT(*) AS source_rows,
          COUNT(DISTINCT invoice_no) AS distinct_invoices,
          COUNT(DISTINCT stock_code) AS distinct_stock_codes,
          COUNT(DISTINCT country) AS distinct_countries,
          SUM(CASE WHEN customer_id IS NULL THEN 1 ELSE 0 END) AS missing_customer_rows,
          SUM(CASE WHEN invoice_ts IS NULL THEN 1 ELSE 0 END) AS missing_invoice_timestamp_rows,
          SUM(CASE WHEN is_cancellation THEN 1 ELSE 0 END) AS cancellation_rows,
          SUM(CASE WHEN quantity <= 0 THEN 1 ELSE 0 END) AS nonpositive_quantity_rows,
          SUM(CASE WHEN unit_price_gbp <= 0 THEN 1 ELSE 0 END) AS nonpositive_unit_price_rows,
          SUM(CASE WHEN is_purchase_line THEN 1 ELSE 0 END) AS purchase_line_rows,
          SUM(CASE WHEN is_identified_purchase_line THEN 1 ELSE 0 END) AS identified_purchase_line_rows
        FROM source_lines
        """
    ).df().iloc[0].to_dict()
    for field, value in independent_quality.items():
        if int(value) != int(quality[field]):
            raise AssertionError(f"Quality mismatch for {field}: {value} != {quality[field]}")

    independent_daily = con.execute(
        """
        SELECT
          CAST(invoice_ts AS DATE) AS date,
          SUM(line_value_gbp) AS revenue_gbp,
          COUNT(DISTINCT invoice_no) AS orders,
          SUM(quantity) AS units,
          COUNT(*) AS purchase_lines,
          COUNT(DISTINCT CASE WHEN customer_id IS NOT NULL THEN customer_id END) AS active_customers
        FROM source_lines
        WHERE is_purchase_line
        GROUP BY 1
        ORDER BY 1
        """
    ).df()
    independent_daily["date"] = pd.to_datetime(independent_daily["date"])
    full_index = pd.date_range(independent_daily["date"].min(), independent_daily["date"].max(), freq="D")
    independent_daily = (
        independent_daily.set_index("date")
        .reindex(full_index, fill_value=0.0)
        .rename_axis("date")
        .reset_index()
    )
    generated_daily = pd.read_csv(output_dir / "real_daily_metrics.csv", parse_dates=["date"])
    _assert_close_frame(
        generated_daily,
        independent_daily,
        "date",
        ["revenue_gbp", "orders", "units", "purchase_lines", "active_customers"],
    )

    semantic_sql = con.execute(
        """
        SELECT
          SUM(CASE WHEN is_purchase_line THEN line_value_gbp ELSE 0 END) AS current_revenue,
          SUM(CASE WHEN invoice_ts IS NOT NULL AND quantity IS NOT NULL AND unit_price_gbp IS NOT NULL THEN line_value_gbp ELSE 0 END) AS candidate_revenue,
          COUNT(DISTINCT CASE WHEN is_identified_purchase_line THEN customer_id END) AS current_customers,
          COUNT(DISTINCT CASE WHEN invoice_ts IS NOT NULL AND customer_id IS NOT NULL THEN customer_id END) AS candidate_customers
        FROM source_lines
        """
    ).df().iloc[0]
    semantic = pd.read_csv(output_dir / "real_semantic_comparison.csv").set_index("metric")
    expected_semantic = {
        "revenue_gbp": (float(semantic_sql["current_revenue"]), float(semantic_sql["candidate_revenue"])),
        "active_customer_population": (float(semantic_sql["current_customers"]), float(semantic_sql["candidate_customers"])),
    }
    for metric, (current_value, candidate_value) in expected_semantic.items():
        row = semantic.loc[metric]
        if not np.isclose(float(row["current_value"]), current_value, rtol=1e-10, atol=1e-8):
            raise AssertionError(f"Semantic current-value mismatch for {metric}")
        if not np.isclose(float(row["candidate_value"]), candidate_value, rtol=1e-10, atol=1e-8):
            raise AssertionError(f"Semantic candidate-value mismatch for {metric}")
        delta = (candidate_value - current_value) / abs(current_value) if current_value else np.nan
        if not np.isclose(float(row["relative_delta"]), delta, rtol=1e-10, atol=1e-10, equal_nan=True):
            raise AssertionError(f"Semantic delta mismatch for {metric}")
        expected_action = "APPROVE_BACKWARD_COMPATIBLE" if abs(delta) <= float(row["tolerance"]) else "WITHHOLD_AS_DROP_IN_REPLACEMENT"
        if row["replacement_action"] != expected_action:
            raise AssertionError(f"Semantic replacement action mismatch for {metric}")

    generated_backtest = pd.read_csv(output_dir / "real_forecast_backtest.csv")
    generated_evaluations = pd.read_csv(output_dir / "real_forecast_evaluations.csv").set_index("metric")
    for metric in ["revenue_gbp", "orders", "units", "active_customers"]:
        backtest = rolling_origin_seasonal_naive(generated_daily, metric)
        actual_rows = generated_backtest.loc[generated_backtest["metric"].eq(metric)].drop(columns=["metric"]).reset_index(drop=True)
        for column in ["actual", "forecast", "benchmark_forecast", "interval_low", "interval_high", "interval_radius"]:
            if not np.allclose(actual_rows[column], backtest[column], rtol=1e-10, atol=1e-8):
                raise AssertionError(f"Forecast backtest mismatch for {metric}:{column}")
        expected_eval = asdict(evaluate_forecast_plan(metric, backtest, ForecastPlanningGate()))
        stored = generated_evaluations.loc[metric]
        for field in ["mape", "wape", "benchmark_mape", "benchmark_wape", "interval_coverage"]:
            if not np.isclose(float(stored[field]), float(expected_eval[field]), rtol=1e-10, atol=1e-10, equal_nan=True):
                raise AssertionError(f"Forecast evaluation mismatch for {metric}:{field}")
        if bool(stored["approved"]) != bool(expected_eval["approved"]):
            raise AssertionError(f"Forecast decision mismatch for {metric}")

    if int(summary["source_rows"]) != EXPECTED_SOURCE_ROWS:
        raise AssertionError("Summary source row count mismatch")
    if int(manifest["artifact_count"]) != 8:
        raise AssertionError(f"Expected 8 manifested real-data artifacts, got {manifest['artifact_count']}")
    manifest_entries = {entry["path"]: entry for entry in manifest["artifacts"]}
    for name, entry in manifest_entries.items():
        path = output_dir / name
        if not path.exists() or _hash_file(path) != entry["sha256"] or path.stat().st_size != int(entry["bytes"]):
            raise AssertionError(f"Manifest mismatch for {name}")

    print(
        "Real UCI retail validation passed: "
        f"{EXPECTED_SOURCE_ROWS:,} rows, {len(generated_daily)} calendar days, "
        f"semantic actions={semantic['replacement_action'].to_dict()}, "
        f"forecast approvals={int(generated_evaluations['approved'].sum())}/4"
    )


if __name__ == "__main__":
    main()
