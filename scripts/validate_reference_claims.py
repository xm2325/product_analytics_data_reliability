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
REFERENCE_96H_REQUIRED_LATE_EVENTS = 2_718_757
REFERENCE_96H_REQUIRED_REVISION_CELLS = 1_853
REFERENCE_96H_EVIDENCE_DAYS = 1_323


def _as_bool(value: object) -> bool:
    return str(value).lower() == "true"


def validate_reference_claims(root: Path) -> list[str]:
    """Pin deterministic v0.30 public claims separately from generic invariants."""
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
        "watermark_evidence_plan.csv",
        "watermark_evidence_plan_contract.json",
        "watermark_evidence_plan_decision.json",
        "reference_summary.json",
    ]
    if any(not (root / name).is_file() for name in required):
        return ["missing_v030_reference_evidence"]

    grid = pd.read_csv(root / "watermark_policy_grid.csv").sort_values("allowed_lateness_hours").reset_index(drop=True)
    decision = json.loads((root / "watermark_policy_decision.json").read_text(encoding="utf-8"))
    windows = pd.read_csv(root / "watermark_rolling_windows.csv").sort_values("window_index").reset_index(drop=True)
    stability = pd.read_csv(root / "watermark_stability_summary.csv").sort_values("allowed_lateness_hours").reset_index(drop=True)
    stable_decision = json.loads((root / "watermark_stability_decision.json").read_text(encoding="utf-8"))
    uncertainty = pd.read_csv(root / "watermark_uncertainty_summary.csv").sort_values("allowed_lateness_hours").reset_index(drop=True)
    uncertainty_contract = json.loads((root / "watermark_uncertainty_contract.json").read_text(encoding="utf-8"))
    certification_decision = json.loads((root / "watermark_certification_decision.json").read_text(encoding="utf-8"))
    evidence_plan = pd.read_csv(root / "watermark_evidence_plan.csv").sort_values("allowed_lateness_hours").reset_index(drop=True)
    evidence_contract = json.loads((root / "watermark_evidence_plan_contract.json").read_text(encoding="utf-8"))
    evidence_decision = json.loads((root / "watermark_evidence_plan_decision.json").read_text(encoding="utf-8"))
    summary = json.loads((root / "reference_summary.json").read_text(encoding="utf-8"))

    if tuple(grid["allowed_lateness_hours"].astype(float)) != REFERENCE_CANDIDATES:
        failures.append("reference_candidate_grid_changed")

    rows = {float(row["allowed_lateness_hours"]): row for _, row in grid.iterrows()}
    if 24.0 not in rows or 48.0 not in rows:
        failures.append("reference_24_or_48_missing")
        return failures

    row24 = rows[24.0]
    row48 = rows[48.0]
    if _as_bool(row24["feasible"]):
        failures.append("reference_24h_unexpectedly_feasible")
    if not _as_bool(row48["feasible"]):
        failures.append("reference_48h_unexpectedly_infeasible")
    if _as_bool(row24["passes_late_event_fraction"]):
        failures.append("reference_24h_late_fraction_gate_no_longer_fails")
    if _as_bool(row24["passes_revised_metric_cell_fraction"]):
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

    # v0.29 uncertainty layer remains an unchanged prerequisite for v0.30.
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

    # v0.30: distinguish structural/hard-gate failures from evidence-depth gaps.
    plan_rows = {
        float(row["allowed_lateness_hours"]): row for _, row in evidence_plan.iterrows()
    }
    if set(plan_rows) != set(REFERENCE_CANDIDATES):
        failures.append("reference_evidence_plan_candidate_set")
    for hours in (24.0, 48.0, 72.0):
        row = plan_rows.get(hours)
        if row is not None and _as_bool(row["evidence_only_addressable"]):
            failures.append(f"reference_{int(hours)}h_unexpectedly_evidence_only")

    plan96 = plan_rows.get(96.0)
    if plan96 is None:
        failures.append("reference_evidence_plan_missing_96h")
    else:
        if not _as_bool(plan96["evidence_only_addressable"]):
            failures.append("reference_96h_not_evidence_only_addressable")
        if int(plan96["required_late_event_trials"]) != REFERENCE_96H_REQUIRED_LATE_EVENTS:
            failures.append("reference_96h_required_late_trials_changed")
        if int(plan96["required_revised_metric_cells"]) != REFERENCE_96H_REQUIRED_REVISION_CELLS:
            failures.append("reference_96h_required_revision_cells_changed")
        if int(plan96["estimated_calendar_days_for_both_proportions"]) != REFERENCE_96H_EVIDENCE_DAYS:
            failures.append("reference_96h_evidence_days_changed")
        if int(plan96["estimated_calendar_days_for_late_bound"]) <= int(plan96["estimated_calendar_days_for_revision_bound"]):
            failures.append("reference_96h_late_bound_not_bottleneck")

    plan48 = plan_rows.get(48.0)
    if plan48 is not None:
        if _as_bool(plan48["revised_rate_below_budget"]):
            failures.append("reference_48h_revision_rate_unexpectedly_below_budget")
        if _as_bool(plan48["revenue_hard_gate_passes"]):
            failures.append("reference_48h_revenue_gate_unexpectedly_passes")

    plan72 = plan_rows.get(72.0)
    if plan72 is not None:
        if not _as_bool(plan72["late_trial_requirement_exceeds_search_cap"]):
            failures.append("reference_72h_late_requirement_no_longer_exceeds_cap")
        if _as_bool(plan72["revenue_hard_gate_passes"]):
            failures.append("reference_72h_revenue_gate_unexpectedly_passes")

    if int(evidence_contract.get("simultaneous_one_sided_bounds", -1)) != 72:
        failures.append("reference_evidence_plan_bound_count")
    if evidence_contract.get("weighted_score_used") is not False:
        failures.append("reference_evidence_plan_weighted_score")
    if evidence_contract.get("budget_relaxed_for_planning") is not False:
        failures.append("reference_evidence_plan_budget_relaxed")
    if evidence_decision.get("status") != "selected":
        failures.append("reference_evidence_plan_decision_status")
    if float(evidence_decision.get("selected_lateness_hours", -1)) != 96.0:
        failures.append("reference_evidence_plan_selected_not_96h")
    if int(evidence_decision.get("estimated_calendar_days_for_both_proportions", -1)) != REFERENCE_96H_EVIDENCE_DAYS:
        failures.append("reference_evidence_plan_decision_days")
    if evidence_decision.get("weighted_score_used") is not False:
        failures.append("reference_evidence_decision_weighted_score")
    if evidence_decision.get("budget_relaxed_for_planning") is not False:
        failures.append("reference_evidence_decision_budget_relaxed")

    if summary.get("version") != "0.30.0":
        failures.append("reference_summary_version")
    processing = summary.get("processing_time", {})
    point_in_time = processing.get("point_in_time_watermark_calibration", {})
    rolling = processing.get("watermark_stability_decision", {})
    certified = processing.get("watermark_certification_decision", {})
    planned = processing.get("watermark_evidence_plan_decision", {})
    if float(point_in_time.get("selected_lateness_hours", -1)) != 48.0:
        failures.append("reference_summary_point_in_time_watermark")
    if float(rolling.get("selected_lateness_hours", -1)) != 96.0:
        failures.append("reference_summary_stable_watermark")
    if certified.get("status") != "no_candidate_certified_familywise_95":
        failures.append("reference_summary_certification_status")
    if certified.get("selected_lateness_hours") is not None:
        failures.append("reference_summary_unexpected_certified_watermark")
    if float(planned.get("selected_lateness_hours", -1)) != 96.0:
        failures.append("reference_summary_evidence_plan_watermark")
    if int(planned.get("estimated_calendar_days_for_both_proportions", -1)) != REFERENCE_96H_EVIDENCE_DAYS:
        failures.append("reference_summary_evidence_plan_days")

    return failures


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate pinned v0.30 deterministic reference claims")
    parser.add_argument("root", nargs="?", default="build/reference")
    args = parser.parse_args()
    failures = validate_reference_claims(Path(args.root))
    if failures:
        raise SystemExit("Reference-claim validation failed: " + ", ".join(failures))
    print(f"Reference-claim validation passed: {args.root}")


if __name__ == "__main__":
    main()
