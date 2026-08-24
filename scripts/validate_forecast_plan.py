from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd


EXPECTED_APPROVED = {"file_transfer:dau", "notes_app:dau"}
EXPECTED_TOTAL_METRICS = 9
EXPECTED_BACKTEST_POINTS_PER_METRIC = 28
EXPECTED_RECONCILIATION_ROWS_PER_METRIC = 4
EXPECTED_MANIFEST_ARTIFACTS = 47


def _fail(message: str) -> None:
    raise SystemExit(f"Forecast-plan validation failed: {message}")


def _mape(actual: pd.Series, forecast: pd.Series) -> float:
    denom = actual.abs().replace(0, np.nan)
    values = ((actual - forecast).abs() / denom).dropna()
    return float(values.mean()) if len(values) else float("nan")


def _wape(actual: pd.Series, forecast: pd.Series) -> float:
    denominator = float(actual.abs().sum())
    return float((actual - forecast).abs().sum() / denominator) if denominator > 0 else float("nan")


def _radius(training: pd.Series, season: int, alpha: float) -> float:
    residuals = np.abs(
        training.iloc[season:].to_numpy(dtype=float)
        - training.iloc[:-season].to_numpy(dtype=float)
    )
    if len(residuals) == 0:
        _fail("empty interval calibration residuals")
    rank = min(len(residuals), math.ceil((len(residuals) + 1) * (1.0 - alpha)))
    return float(np.sort(residuals)[rank - 1])


def validate(root: Path) -> None:
    required = [
        "gold_daily_metrics.csv",
        "silver_events.csv",
        "forecast_evaluations.csv",
        "forecast_backtest.csv",
        "forecast_reconciliation.csv",
        "forecast_contract.json",
        "reference_summary.json",
        "MANIFEST.json",
    ]
    missing = [name for name in required if not (root / name).is_file()]
    if missing:
        _fail(f"missing artifacts: {missing}")

    contract = json.loads((root / "forecast_contract.json").read_text(encoding="utf-8"))
    if contract.get("version") != "2.0":
        _fail("forecast contract version is not 2.0")
    if contract.get("weighted_score_used") is not False:
        _fail("weighted score must remain disabled")
    if contract.get("future_data_leakage_allowed") is not False:
        _fail("future-data leakage flag must remain false")
    if int(contract.get("rolling_origins", -1)) != 4 or int(contract.get("horizon_days", -1)) != 7:
        _fail("reference rolling-origin geometry changed")
    gate = contract.get("planning_gate", {})
    if float(gate.get("max_mape", -1)) != 0.20 or float(gate.get("max_wape", -1)) != 0.20:
        _fail("absolute accuracy gate changed")
    if float(gate.get("min_interval_coverage", -1)) != 0.85:
        _fail("interval coverage gate changed")
    if gate.get("require_noninferior_wape_to_benchmark") is not True:
        _fail("benchmark non-inferiority gate changed")

    gold = pd.read_csv(root / "gold_daily_metrics.csv")
    gold["date"] = pd.to_datetime(gold["date"], errors="raise")
    silver = pd.read_csv(root / "silver_events.csv")
    silver["event_ts"] = pd.to_datetime(silver["event_ts"], utc=True, errors="raise")
    evaluations = pd.read_csv(root / "forecast_evaluations.csv")
    backtest = pd.read_csv(root / "forecast_backtest.csv")
    reconciliation = pd.read_csv(root / "forecast_reconciliation.csv")

    if len(evaluations) != EXPECTED_TOTAL_METRICS:
        _fail(f"expected {EXPECTED_TOTAL_METRICS} evaluation rows, got {len(evaluations)}")
    if len(backtest) != EXPECTED_TOTAL_METRICS * EXPECTED_BACKTEST_POINTS_PER_METRIC:
        _fail("unexpected row-level backtest size")
    if len(reconciliation) != EXPECTED_TOTAL_METRICS * EXPECTED_RECONCILIATION_ROWS_PER_METRIC:
        _fail("unexpected reconciliation size")

    evaluation_by_metric = evaluations.set_index("metric")
    approved = set(evaluations.loc[evaluations["approved"].astype(str).str.lower().eq("true"), "metric"])
    if approved != EXPECTED_APPROVED:
        _fail(f"approved metric set changed: {sorted(approved)}")

    season = int(contract["season_days"])
    horizon = int(contract["horizon_days"])
    origins = int(contract["rolling_origins"])
    alpha = 1.0 - float(contract["interval_nominal_coverage"])

    for product in sorted(gold["product"].unique()):
        boundary = silver.loc[
            silver["product"].eq(product) & silver["event_type"].eq("first_open"),
            "event_ts",
        ]
        if boundary.empty:
            _fail(f"missing first_open boundary for {product}")
        cutoff = pd.to_datetime(boundary, utc=True).dt.normalize().max().tz_localize(None)
        product_history = gold.loc[
            gold["product"].eq(product) & gold["date"].le(cutoff)
        ].sort_values("date").reset_index(drop=True)

        for raw_metric in ("dau", "revenue_gbp", "paid_subscription"):
            metric = f"{product}:{raw_metric}"
            rows = backtest.loc[backtest["metric"].eq(metric)].sort_values(
                ["origin_index", "horizon_day"]
            ).reset_index(drop=True)
            if len(rows) != EXPECTED_BACKTEST_POINTS_PER_METRIC:
                _fail(f"{metric}: wrong number of backtest rows")

            y = product_history[raw_metric].astype(float).reset_index(drop=True)
            dates = product_history["date"].reset_index(drop=True)
            starts = list(range(len(y) - origins * horizon, len(y), horizon))
            expected_rows = []
            for origin_index, start in enumerate(starts, start=1):
                training = y.iloc[:start]
                radius = _radius(training, season, alpha)
                benchmark = float(training.iloc[-1])
                origin_date = dates.iloc[start - 1]
                for horizon_day in range(1, horizon + 1):
                    target_index = start + horizon_day - 1
                    source_index = target_index - season
                    if source_index >= start:
                        _fail(f"{metric}: seasonal source leaks future information")
                    point = float(y.iloc[source_index])
                    actual = float(y.iloc[target_index])
                    expected_rows.append(
                        {
                            "origin_index": origin_index,
                            "origin_date": origin_date.date().isoformat(),
                            "target_date": dates.iloc[target_index].date().isoformat(),
                            "seasonal_source_date": dates.iloc[source_index].date().isoformat(),
                            "horizon_day": horizon_day,
                            "actual": actual,
                            "forecast": point,
                            "benchmark_forecast": benchmark,
                            "interval_low": max(0.0, point - radius),
                            "interval_high": point + radius,
                            "interval_radius": radius,
                            "calibration_points": len(training) - season,
                        }
                    )
            expected = pd.DataFrame(expected_rows)

            for column in [
                "origin_index",
                "origin_date",
                "target_date",
                "seasonal_source_date",
                "horizon_day",
                "calibration_points",
            ]:
                if rows[column].astype(str).tolist() != expected[column].astype(str).tolist():
                    _fail(f"{metric}: {column} differs from independent reconstruction")
            for column in [
                "actual",
                "forecast",
                "benchmark_forecast",
                "interval_low",
                "interval_high",
                "interval_radius",
            ]:
                if not np.allclose(rows[column].astype(float), expected[column].astype(float), rtol=0.0, atol=1e-12):
                    _fail(f"{metric}: {column} differs from independent reconstruction")

            if not (
                pd.to_datetime(rows["seasonal_source_date"]) <= pd.to_datetime(rows["origin_date"])
            ).all():
                _fail(f"{metric}: source date after origin")
            if not (pd.to_datetime(rows["target_date"]) > pd.to_datetime(rows["origin_date"])).all():
                _fail(f"{metric}: target date not strictly after origin")

            actual = rows["actual"].astype(float)
            forecast = rows["forecast"].astype(float)
            benchmark_values = rows["benchmark_forecast"].astype(float)
            mape = _mape(actual, forecast)
            wape = _wape(actual, forecast)
            benchmark_mape = _mape(actual, benchmark_values)
            benchmark_wape = _wape(actual, benchmark_values)
            coverage = float(
                (
                    actual.ge(rows["interval_low"].astype(float))
                    & actual.le(rows["interval_high"].astype(float))
                ).mean()
            )
            expected_approved = bool(
                len(rows) >= int(gate["min_backtest_points"])
                and mape <= float(gate["max_mape"])
                and wape <= float(gate["max_wape"])
                and wape <= benchmark_wape + 1e-15
                and coverage >= float(gate["min_interval_coverage"])
            )
            reported = evaluation_by_metric.loc[metric]
            comparisons = {
                "mape": mape,
                "wape": wape,
                "benchmark_mape": benchmark_mape,
                "benchmark_wape": benchmark_wape,
                "interval_coverage": coverage,
            }
            for column, expected_value in comparisons.items():
                if not math.isclose(float(reported[column]), expected_value, rel_tol=0.0, abs_tol=1e-12):
                    _fail(f"{metric}: {column} mismatch")
            reported_approved = str(reported["approved"]).lower() == "true"
            if reported_approved != expected_approved:
                _fail(f"{metric}: approval state mismatch")

            recon = reconciliation.loc[reconciliation["metric"].eq(metric)].sort_values("origin_index")
            for origin_index, origin_rows in rows.groupby("origin_index", sort=True):
                recon_row = recon.loc[recon["origin_index"].eq(origin_index)]
                if len(recon_row) != 1:
                    _fail(f"{metric}: missing reconciliation row for origin {origin_index}")
                recon_row = recon_row.iloc[0]
                planned_total = float(origin_rows["forecast"].sum())
                actual_total = float(origin_rows["actual"].sum())
                if not math.isclose(float(recon_row["planned_total"]), planned_total, abs_tol=1e-12):
                    _fail(f"{metric}: planned total mismatch")
                if not math.isclose(float(recon_row["actual_total"]), actual_total, abs_tol=1e-12):
                    _fail(f"{metric}: actual total mismatch")

    photo = evaluation_by_metric.loc["photo_editor:dau"]
    if not bool(str(photo["absolute_accuracy_gate"]).lower() == "true"):
        _fail("photo_editor:dau should pass absolute accuracy")
    if bool(str(photo["benchmark_gate"]).lower() == "true"):
        _fail("photo_editor:dau should be withheld by benchmark gate")
    if not (float(photo["wape"]) > float(photo["benchmark_wape"])):
        _fail("photo_editor:dau benchmark counterexample disappeared")

    summary = json.loads((root / "reference_summary.json").read_text(encoding="utf-8"))
    if summary.get("version") != "0.34.0":
        _fail(f"reference summary version is {summary.get('version')}")
    if int(summary["forecast_gate"]["approved"]) != 2 or int(summary["forecast_gate"]["withheld"]) != 7:
        _fail("reference summary forecast gate is not 2 approved / 7 withheld")
    if set(summary["forecast_gate"]["approved_metrics"]) != EXPECTED_APPROVED:
        _fail("reference summary approved metric set changed")

    manifest = json.loads((root / "MANIFEST.json").read_text(encoding="utf-8"))
    if int(manifest["artifact_count"]) != EXPECTED_MANIFEST_ARTIFACTS:
        _fail(f"manifest artifact count is {manifest['artifact_count']}, expected {EXPECTED_MANIFEST_ARTIFACTS}")

    print(f"Forecast-plan validation passed: {root}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Independently validate v0.34 forecast decision evidence")
    parser.add_argument("root", nargs="?", default="build/reference")
    args = parser.parse_args()
    validate(Path(args.root))


if __name__ == "__main__":
    main()
