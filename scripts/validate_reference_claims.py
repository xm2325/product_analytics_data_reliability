from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import pandas as pd


REFERENCE_CANDIDATES = (24.0, 48.0, 72.0, 96.0)
REFERENCE_WINDOW_SELECTIONS = (72.0, 72.0, 72.0, 96.0, 48.0, 48.0, 48.0, 48.0, 48.0)
REFERENCE_FEASIBLE_WINDOWS = {24.0: 0, 48.0: 5, 72.0: 8, 96.0: 9}
REFERENCE_CERTIFIED_WINDOWS = {24.0: 0, 48.0: 0, 72.0: 0, 96.0: 0}
REFERENCE_96H_LATE_UPPER = 0.005485099103662166
REFERENCE_96H_REVISION_UPPER = 0.017385209176541436


def validate_reference_claims(root: Path) -> list[str]:
    """Pin deterministic v0.29 public claims separately from generic invariants."""
    failures: list[str] = []
    required = [
        "watermark_policy_grid.csv",
        "watermark_policy_decision.json",
        "watermark_rolling_windows.csv",
        "watermark_stability_summary.csv",
        "watermark_stability_decision.json",
        "watermark_uncertainty_summary.csv",
        "watermark_uncertainty_contract.json",
        "watermark_certification_decision.json",
        "reference_summary.json",
    ]
    if any(not (root / name).is_file() for name in required):
        return ["missing_v029_reference_evidence"]

    grid = pd.read_csv(root / "watermark_policy_grid.csv").sort_values("allowed_lateness_hours").reset_index(drop=True)
    decision = json.loads((root / "watermark_policy_decision.json").read_text(encoding="utf-8"))
    windows = pd.read_csv(root / "watermark_rolling_windows.csv").sort_values("window_index").reset_index(drop=True)
    stability = pd.read_csv(root / "watermark_stability_summary.csv").sort_values("allowed_lateness_hours").reset_index(drop=True)
    stable_decision = json.loads((root / "watermark_stability_decision.json").read_text(encoding="utf-8"))
    uncertainty = pd.read_csv(root / "watermark_uncertainty_summary.csv").sort_values("allowed_lateness_hours").reset_index(drop=True)
    uncertainty_contract = json.loads((root / "watermark_uncertainty_contract.json").read_text(encoding="utf-8"))
    certification_decision = json.loads((root / "watermark_certification_decision.json").read_text(encoding="utf-8"))
    summary = json.loads((root / "reference_summary.json").read_text(encoding="utf-8"))

    if tuple(grid["allowed_lateness_hours"].astype(float)) != REFERENCE_CANDIDATES:
        failures.append("reference_candidate_grid_changed")

    rows = {float(row["allowed_lateness_hours"]): row for _, row in grid.iterrows()}
    if 24.0 not in rows or 48.0 not in rows:
        failures.append("reference_24_or_48_missing")
        return failures

    row24 = rows[24.0]
    row48 = rows[48.0]
    if str(row24["feasible"]).lower() == "true":
        failures.append("reference_24h_unexpectedly_feasible")
    if str(row48["feasible"]).lower() != "true":
        failures.append("reference_48h_unexpectedly_infeasible")
    if str(row24["passes_late_event_fraction"]).lower() != "false":
        failures.append("reference_24h_late_fraction_gate_no_longer_fails")
    if str(row24["passes_revised_metric_cell_fraction"]).lower() != "false":
        failures.append("reference_24h_revision_fraction_gate_no_longer_fails")

    if float(decision.get("selected_lateness_hours", -1)) != 48.0:
        failures.append("reference_point_in_time_selected_watermark_not_48h")
    if decision.get("weighted_score_used") is not False:
        failures.append("reference_point_in_time_selector_used_weighted_score")
    if decision.get("late_event_fraction_scope") != "event_date_on_or_before_candidate_watermark":
        failures.append("reference_point_in_time_scope_not_finalizable_events")

    observed_window_selections = tuple(windows["selected_lateness_hours"].astype(float))
    if observed_window_selections != REFERENCE_WINDOW_SELECTIONS:
        failures.append("reference_rolling_window_selection_sequence_changed")
    if len(windows) != 9:
        failures.append("reference_rolling_window_count_changed")

    stable_rows = {float(row["allowed_lateness_hours"]): row for _, row in stability.iterrows()}
    for hours, expected_feasible in REFERENCE_FEASIBLE_WINDOWS.items():
        row = stable_rows.get(hours)
        if row is None:
            failures.append(f"reference_stability_missing_{int(hours)}h")
            continue
        if int(row["feasible_windows"]) != expected_feasible:
            failures.append(f"reference_feasible_window_count_changed_{int(hours)}h")

    if stable_decision.get("status") != "selected":
        failures.append("reference_stable_policy_not_selected")
    if float(stable_decision.get("selected_lateness_hours", -1)) != 96.0:
        failures.append("reference_stable_selected_watermark_not_96h")
    if stable_decision.get("weighted_score_used") is not False:
        failures.append("reference_stable_selector_used_weighted_score")
    if stable_decision.get("budget_relaxed_after_backtest") is not False:
        failures.append("reference_budget_was_relaxed_after_backtest")

    # v0.29: observed 96h stability is not enough for simultaneous statistical
    # certification. All 72 one-sided proportion bounds share a 95% Bonferroni
    # family, so every candidate currently has zero certified windows.
    if uncertainty_contract.get("correction") != "bonferroni":
        failures.append("reference_uncertainty_correction")
    if not math.isclose(float(uncertainty_contract.get("family_confidence_level", -1)), 0.95, abs_tol=1e-15):
        failures.append("reference_uncertainty_family_confidence")
    if int(uncertainty_contract.get("simultaneous_one_sided_bounds", -1)) != 72:
        failures.append("reference_uncertainty_bound_count")
    if not math.isclose(
        float(uncertainty_contract.get("per_bound_alpha", -1)),
        0.05 / 72.0,
        rel_tol=0.0,
        abs_tol=1e-15,
    ):
        failures.append("reference_uncertainty_per_bound_alpha")
    if uncertainty_contract.get("weighted_score_used") is not False:
        failures.append("reference_uncertainty_weighted_score")

    uncertainty_rows = {
        float(row["allowed_lateness_hours"]): row for _, row in uncertainty.iterrows()
    }
    for hours, expected_certified in REFERENCE_CERTIFIED_WINDOWS.items():
        row = uncertainty_rows.get(hours)
        if row is None:
            failures.append(f"reference_uncertainty_missing_{int(hours)}h")
            continue
        if int(row["certified_windows"]) != expected_certified:
            failures.append(f"reference_certified_window_count_changed_{int(hours)}h")

    row96 = uncertainty_rows.get(96.0)
    if row96 is not None:
        if not math.isclose(
            float(row96["max_late_event_fraction_upper"]),
            REFERENCE_96H_LATE_UPPER,
            rel_tol=0.0,
            abs_tol=1e-12,
        ):
            failures.append("reference_96h_late_upper_changed")
        if not math.isclose(
            float(row96["max_revised_metric_cell_fraction_upper"]),
            REFERENCE_96H_REVISION_UPPER,
            rel_tol=0.0,
            abs_tol=1e-12,
        ):
            failures.append("reference_96h_revision_upper_changed")
        if float(row96["max_late_event_fraction_upper"]) <= 0.005:
            failures.append("reference_96h_late_upper_no_longer_breaches")
        if float(row96["max_revised_metric_cell_fraction_upper"]) <= 0.01:
            failures.append("reference_96h_revision_upper_no_longer_breaches")

    if certification_decision.get("status") != "no_candidate_certified_familywise_95":
        failures.append("reference_certification_status")
    if certification_decision.get("selected_lateness_hours") is not None:
        failures.append("reference_unexpected_certified_watermark")
    if certification_decision.get("weighted_score_used") is not False:
        failures.append("reference_certification_weighted_score")
    if certification_decision.get("budget_relaxed_after_uncertainty") is not False:
        failures.append("reference_uncertainty_budget_relaxed")

    if summary.get("version") != "0.29.0":
        failures.append("reference_summary_version")
    processing = summary.get("processing_time", {})
    point_in_time = processing.get("point_in_time_watermark_calibration", {})
    rolling = processing.get("watermark_stability_decision", {})
    certified = processing.get("watermark_certification_decision", {})
    if float(point_in_time.get("selected_lateness_hours", -1)) != 48.0:
        failures.append("reference_summary_point_in_time_watermark")
    if float(rolling.get("selected_lateness_hours", -1)) != 96.0:
        failures.append("reference_summary_stable_watermark")
    if certified.get("status") != "no_candidate_certified_familywise_95":
        failures.append("reference_summary_certification_status")
    if certified.get("selected_lateness_hours") is not None:
        failures.append("reference_summary_unexpected_certified_watermark")

    return failures


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate pinned v0.29 deterministic reference claims")
    parser.add_argument("root", nargs="?", default="build/reference")
    args = parser.parse_args()
    failures = validate_reference_claims(Path(args.root))
    if failures:
        raise SystemExit("Reference-claim validation failed: " + ", ".join(failures))
    print(f"Reference-claim validation passed: {args.root}")


if __name__ == "__main__":
    main()
