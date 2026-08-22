from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd


CANDIDATES = {24.0, 48.0, 72.0, 96.0}


def _as_bool(values: pd.Series) -> pd.Series:
    return values.astype(str).str.lower().eq("true")


def validate_watermark_backtest(root: Path) -> list[str]:
    failures: list[str] = []
    required = [
        "watermark_policy_grid.csv",
        "watermark_policy_decision.json",
        "watermark_rolling_grid.csv",
        "watermark_rolling_windows.csv",
        "watermark_stability_summary.csv",
        "watermark_stability_decision.json",
    ]
    missing = [name for name in required if not (root / name).is_file()]
    if missing:
        return [f"missing:{name}" for name in missing]

    point = pd.read_csv(root / "watermark_policy_grid.csv").sort_values("allowed_lateness_hours").reset_index(drop=True)
    if set(point["allowed_lateness_hours"].astype(float)) != CANDIDATES or len(point) != len(CANDIDATES):
        failures.append("point_candidate_set")
    required_point_columns = {
        "settled_stream_events",
        "finalizable_events",
        "late_event_fraction",
        "whole_stream_late_event_fraction",
        "revised_metric_cell_fraction",
        "feasible",
    }
    if not required_point_columns.issubset(point.columns):
        failures.append("point_scope_columns")
    else:
        if not point["finalizable_events"].le(point["settled_stream_events"]).all():
            failures.append("finalizable_events_exceed_settled_stream")
        if not point["finalizable_events"].is_monotonic_decreasing:
            failures.append("finalizable_events_not_monotone")
        if not point["whole_stream_late_event_fraction"].is_monotonic_decreasing:
            failures.append("whole_stream_late_fraction_not_monotone")
        if not point["late_event_fraction"].between(0, 1).all():
            failures.append("point_late_fraction_bounds")
        if not point["revised_metric_cell_fraction"].between(0, 1).all():
            failures.append("point_revision_fraction_bounds")

    point_decision = json.loads((root / "watermark_policy_decision.json").read_text(encoding="utf-8"))
    if point_decision.get("weighted_score_used") is not False:
        failures.append("point_weighted_score_used")
    if point_decision.get("late_event_fraction_scope") != "event_date_on_or_before_candidate_watermark":
        failures.append("point_decision_scope")
    feasible_point = point.loc[_as_bool(point["feasible"])]
    if feasible_point.empty:
        if point_decision.get("status") != "no_candidate_meets_budget":
            failures.append("point_empty_feasible_status")
    else:
        expected = float(feasible_point["allowed_lateness_hours"].min())
        if float(point_decision.get("selected_lateness_hours", -1)) != expected:
            failures.append("point_not_shortest_feasible")

    rolling = pd.read_csv(root / "watermark_rolling_grid.csv")
    windows = pd.read_csv(root / "watermark_rolling_windows.csv")
    stability = pd.read_csv(root / "watermark_stability_summary.csv").sort_values("allowed_lateness_hours").reset_index(drop=True)
    stable_decision = json.loads((root / "watermark_stability_decision.json").read_text(encoding="utf-8"))

    window_ids = sorted(rolling["window_index"].unique())
    if len(window_ids) < 2:
        failures.append("rolling_too_few_windows")
    if len(windows) != len(window_ids):
        failures.append("rolling_window_table_count")
    for window_id, frame in rolling.groupby("window_index"):
        if set(frame["allowed_lateness_hours"].astype(float)) != CANDIDATES:
            failures.append(f"rolling_candidate_set_window_{window_id}")
        if len(frame) != len(CANDIDATES):
            failures.append(f"rolling_candidate_count_window_{window_id}")
        ordered = frame.sort_values("allowed_lateness_hours")
        if not ordered["finalizable_events"].is_monotonic_decreasing:
            failures.append(f"rolling_finalizable_not_monotone_window_{window_id}")
        if not ordered["whole_stream_late_event_fraction"].is_monotonic_decreasing:
            failures.append(f"rolling_whole_stream_late_not_monotone_window_{window_id}")

        feasible = ordered.loc[_as_bool(ordered["feasible"])]
        window_row = windows.loc[windows["window_index"].eq(window_id)]
        if len(window_row) != 1:
            failures.append(f"rolling_window_row_{window_id}")
            continue
        selected = pd.to_numeric(window_row.iloc[0]["selected_lateness_hours"], errors="coerce")
        if feasible.empty:
            if pd.notna(selected):
                failures.append(f"rolling_unexpected_selection_window_{window_id}")
        else:
            expected = float(feasible["allowed_lateness_hours"].min())
            if pd.isna(selected) or float(selected) != expected:
                failures.append(f"rolling_not_shortest_feasible_window_{window_id}")

    if set(stability["allowed_lateness_hours"].astype(float)) != CANDIDATES:
        failures.append("stability_candidate_set")
    if not stability["windows"].eq(len(window_ids)).all():
        failures.append("stability_window_count")
    if not (stability["feasible_windows"] <= stability["windows"]).all():
        failures.append("stability_feasible_count_bounds")
    expected_rate = stability["feasible_windows"] / stability["windows"]
    if not (stability["feasibility_rate"] - expected_rate).abs().lt(1e-12).all():
        failures.append("stability_rate_accounting")
    stable_flag = _as_bool(stability["stable_all_windows"])
    if not stable_flag.eq(stability["feasible_windows"].eq(stability["windows"])).all():
        failures.append("stability_all_windows_flag")

    if stable_decision.get("weighted_score_used") is not False:
        failures.append("stable_weighted_score_used")
    if stable_decision.get("budget_relaxed_after_backtest") is not False:
        failures.append("stable_budget_relaxed")
    stable_rows = stability.loc[stable_flag]
    if stable_rows.empty:
        if stable_decision.get("status") != "no_candidate_stable_in_all_windows":
            failures.append("stable_empty_status")
        if stable_decision.get("selected_lateness_hours") is not None:
            failures.append("stable_empty_selection")
    else:
        expected = float(stable_rows["allowed_lateness_hours"].min())
        if stable_decision.get("status") != "selected":
            failures.append("stable_selected_status")
        if float(stable_decision.get("selected_lateness_hours", -1)) != expected:
            failures.append("stable_not_shortest_all_window_feasible")

    return failures


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate watermark calibration and rolling stability artifacts")
    parser.add_argument("root", nargs="?", default="build/reference")
    args = parser.parse_args()
    failures = validate_watermark_backtest(Path(args.root))
    if failures:
        raise SystemExit("Watermark-backtest validation failed: " + ", ".join(failures))
    print(f"Watermark-backtest validation passed: {args.root}")


if __name__ == "__main__":
    main()
