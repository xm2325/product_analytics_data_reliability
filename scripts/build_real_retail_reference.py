from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path

from product_analytics.real_retail import (
    REAL_DATA_METRIC_TOLERANCE,
    UCI_ONLINE_RETAIL_II_URL,
    build_daily_metrics,
    download_source,
    extract_workbook,
    forecast_real_metrics,
    load_workbook,
    quality_report,
    semantic_comparison,
    source_provenance,
    write_json,
)


def _sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the v0.36 UCI Online Retail II real-data evidence lane")
    parser.add_argument("--output-dir", type=Path, default=Path("build/real-retail"))
    parser.add_argument("--source-archive", type=Path, default=None)
    args = parser.parse_args()

    output_dir = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    source_dir = output_dir / "_source"
    source_dir.mkdir(parents=True, exist_ok=True)

    archive_path = args.source_archive or source_dir / "online_retail_ii.zip"
    if args.source_archive is None:
        download_source(archive_path)
    if not archive_path.exists():
        raise FileNotFoundError(archive_path)

    workbook_path = extract_workbook(archive_path, source_dir / "extracted")
    canonical, sheets = load_workbook(workbook_path)

    quality = quality_report(canonical, sheets)
    daily = build_daily_metrics(canonical)
    semantic = semantic_comparison(canonical)
    forecast_backtest, forecast_evaluations = forecast_real_metrics(daily)
    provenance = source_provenance(archive_path, workbook_path, sheets)

    metric_contract = {
        "version": "0.36.0",
        "source": "UCI Online Retail II",
        "purchase_line_rule": "invoice is not a cancellation AND quantity > 0 AND unit price > 0 AND invoice timestamp is present",
        "revenue_gbp": "sum(quantity * unit_price_gbp) over valid purchase lines",
        "orders": "unique invoice numbers among valid purchase lines",
        "units": "sum quantity over valid purchase lines",
        "purchase_lines": "count of valid purchase lines",
        "active_customers": "unique non-null customer IDs among valid purchase lines",
        "calendar_rule": "continuous calendar from first to last observed valid purchase date; no-sale dates are explicit zeros",
        "semantic_replay": {
            "tolerance": REAL_DATA_METRIC_TOLERANCE,
            "purpose": "test backward compatibility of a proposed drop-in metric replacement; it does not assert that alternative metric definitions are intrinsically wrong",
        },
        "forecast_rule": "reuse v0.35 leakage-safe four-origin, seven-day weekly-seasonal-naive candidate vs last-value benchmark without retuning on the real dataset",
        "ingestion_timestamp_available": False,
        "watermark_or_late_arrival_validation": "not applicable: the public source exposes invoice event time but no ingestion/processing time",
    }

    daily.to_csv(output_dir / "real_daily_metrics.csv", index=False)
    semantic.to_csv(output_dir / "real_semantic_comparison.csv", index=False)
    forecast_backtest.to_csv(output_dir / "real_forecast_backtest.csv", index=False)
    forecast_evaluations.to_csv(output_dir / "real_forecast_evaluations.csv", index=False)
    write_json(output_dir / "real_source_provenance.json", provenance)
    write_json(output_dir / "real_quality_report.json", quality)
    write_json(output_dir / "real_metric_contract.json", metric_contract)

    summary = {
        "version": "0.36.0",
        "dataset": "UCI Online Retail II",
        "source_rows": quality["source_rows"],
        "date_min": quality["date_min"],
        "date_max": quality["date_max"],
        "calendar_days": int(len(daily)),
        "purchase_line_rows": quality["purchase_line_rows"],
        "missing_customer_rows": quality["missing_customer_rows"],
        "cancellation_rows": quality["cancellation_rows"],
        "semantic_actions": dict(zip(semantic["metric"], semantic["replacement_action"])),
        "forecast_approved": int(forecast_evaluations["approved"].sum()),
        "forecast_withheld": int((~forecast_evaluations["approved"]).sum()),
        "raw_source_committed_to_repository": False,
        "source_archive_sha256": provenance["archive_sha256"],
    }
    write_json(output_dir / "real_data_summary.json", summary)

    artifact_paths = sorted(
        path
        for path in output_dir.iterdir()
        if path.is_file() and path.name.startswith("real_") and path.name != "real_manifest.json"
    )
    manifest = {
        "algorithm": "sha256",
        "artifact_count": len(artifact_paths),
        "artifacts": [
            {"path": path.name, "bytes": path.stat().st_size, "sha256": _sha256(path)}
            for path in artifact_paths
        ],
    }
    write_json(output_dir / "real_manifest.json", manifest)

    print(json.dumps(summary, indent=2, sort_keys=True))
    print(f"real-data evidence artifacts: {len(artifact_paths)}")
    print(f"source: {UCI_ONLINE_RETAIL_II_URL}")


if __name__ == "__main__":
    main()
