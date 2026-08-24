from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from product_analytics.real_source_contract import (
    UCI_ONLINE_RETAIL_II_ARCHIVE_SHA256,
    UCI_ONLINE_RETAIL_II_WORKBOOK_SHA256,
)


def _load_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def _require_close(actual: object, expected: str, claim: str) -> None:
    if not np.isclose(float(actual), float(expected), rtol=1e-10, atol=1e-10):
        raise AssertionError(f"Real-data claim mismatch for {claim}: {actual} != {expected}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate checked-in v0.36 real-data public claims")
    parser.add_argument("output_dir", type=Path)
    parser.add_argument(
        "--ledger",
        type=Path,
        default=Path("results/real_data_reference_summary.csv"),
    )
    args = parser.parse_args()

    ledger_df = pd.read_csv(args.ledger, dtype=str)
    if ledger_df["claim"].duplicated().any():
        raise AssertionError("Duplicate claim names in real-data ledger")
    ledger = dict(zip(ledger_df["claim"], ledger_df["value"]))

    summary = _load_json(args.output_dir / "real_data_summary.json")
    quality = _load_json(args.output_dir / "real_quality_report.json")
    provenance = _load_json(args.output_dir / "real_source_provenance.json")
    semantic = pd.read_csv(args.output_dir / "real_semantic_comparison.csv").set_index("metric")
    forecasts = pd.read_csv(args.output_dir / "real_forecast_evaluations.csv").set_index("metric")

    exact = {
        "version": summary["version"],
        "source_rows": summary["source_rows"],
        "calendar_days": summary["calendar_days"],
        "missing_customer_rows": quality["missing_customer_rows"],
        "cancellation_rows": quality["cancellation_rows"],
        "purchase_line_rows": quality["purchase_line_rows"],
        "revenue_semantic_action": semantic.loc["revenue_gbp", "replacement_action"],
        "customer_population_semantic_action": semantic.loc["active_customer_population", "replacement_action"],
        "forecast_approved": summary["forecast_approved"],
        "forecast_withheld": summary["forecast_withheld"],
        "source_archive_sha256": provenance["archive_sha256"],
        "workbook_sha256": provenance["workbook_sha256"],
    }
    for claim, actual in exact.items():
        if str(actual) != ledger[claim]:
            raise AssertionError(f"Real-data claim mismatch for {claim}: {actual} != {ledger[claim]}")

    numeric = {
        "revenue_semantic_delta": semantic.loc["revenue_gbp", "relative_delta"],
        "customer_population_semantic_delta": semantic.loc["active_customer_population", "relative_delta"],
        "revenue_mape": forecasts.loc["revenue_gbp", "mape"],
        "revenue_wape": forecasts.loc["revenue_gbp", "wape"],
        "orders_mape": forecasts.loc["orders", "mape"],
        "orders_wape": forecasts.loc["orders", "wape"],
        "units_mape": forecasts.loc["units", "mape"],
        "units_wape": forecasts.loc["units", "wape"],
        "active_customers_mape": forecasts.loc["active_customers", "mape"],
        "active_customers_wape": forecasts.loc["active_customers", "wape"],
    }
    for claim, actual in numeric.items():
        _require_close(actual, ledger[claim], claim)

    if ledger["source_archive_sha256"] != UCI_ONLINE_RETAIL_II_ARCHIVE_SHA256:
        raise AssertionError("Checked-in source archive claim does not match pinned source contract")
    if ledger["workbook_sha256"] != UCI_ONLINE_RETAIL_II_WORKBOOK_SHA256:
        raise AssertionError("Checked-in workbook claim does not match pinned source contract")

    if bool(forecasts["approved"].any()):
        raise AssertionError("Public real-data claim expects all four frozen forecast decisions withheld")

    print(f"Real-data static-claim validation passed: {args.ledger}")


if __name__ == "__main__":
    main()
