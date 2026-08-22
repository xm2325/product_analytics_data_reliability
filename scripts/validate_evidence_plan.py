from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd


REQUIRED_ARTIFACTS = {
    "watermark_evidence_plan.csv",
    "watermark_evidence_plan_contract.json",
    "watermark_evidence_plan_decision.json",
}


def _as_bool(series: pd.Series) -> pd.Series:
    return series.astype(str).str.lower().eq("true")


def validate_evidence_plan(root: Path) -> list[str]:
    failures: list[str] = []
    missing = sorted(name for name in REQUIRED_ARTIFACTS if not (root / name).is_file())
    if missing:
        return [f"missing:{name}" for name in missing]

    plan = pd.read_csv(root / "watermark_evidence_plan.csv").sort_values("allowed_lateness_hours")
    contract = json.loads((root / "watermark_evidence_plan_contract.json").read_text(encoding="utf-8"))
    decision = json.loads((root / "watermark_evidence_plan_decision.json").read_text(encoding="utf-8"))

    if set(plan["allowed_lateness_hours"].astype(float)) != {24.0, 48.0, 72.0, 96.0}:
        failures.append("evidence_plan_candidate_set")
    if len(plan) != 4:
        failures.append("evidence_plan_row_count")

    required_columns = {
        "planning_late_event_rate",
        "planning_revised_metric_cell_rate",
        "late_rate_below_budget",
        "revised_rate_below_budget",
        "revenue_hard_gate_passes",
        "paid_hard_gate_passes",
        "required_late_event_trials",
        "required_revised_metric_cells",
        "median_finalizable_events_per_day",
        "median_metric_cells_per_day",
        "estimated_calendar_days_for_both_proportions",
        "evidence_only_addressable",
        "planning_interpretation",
    }
    if not required_columns.issubset(plan.columns):
        failures.append("evidence_plan_columns")
        return failures

    evidence_only = _as_bool(plan["evidence_only_addressable"])
    component = (
        _as_bool(plan["late_rate_below_budget"])
        & _as_bool(plan["revised_rate_below_budget"])
        & _as_bool(plan["revenue_hard_gate_passes"])
        & _as_bool(plan["paid_hard_gate_passes"])
    )
    if not evidence_only.eq(component).all():
        failures.append("evidence_only_component_accounting")

    if (plan["median_finalizable_events_per_day"] <= 0).any():
        failures.append("nonpositive_event_throughput")
    if (plan["median_metric_cells_per_day"] <= 0).any():
        failures.append("nonpositive_metric_throughput")

    eligible = plan.loc[evidence_only]
    if not eligible.empty:
        if eligible["required_late_event_trials"].isna().any():
            failures.append("eligible_missing_late_trials")
        if eligible["required_revised_metric_cells"].isna().any():
            failures.append("eligible_missing_revision_trials")
        if eligible["estimated_calendar_days_for_both_proportions"].isna().any():
            failures.append("eligible_missing_calendar_days")

    rate_fail = ~_as_bool(plan["late_rate_below_budget"])
    if plan.loc[rate_fail, "required_late_event_trials"].notna().any():
        failures.append("rate_breach_given_late_sample_plan")
    revision_rate_fail = ~_as_bool(plan["revised_rate_below_budget"])
    if plan.loc[revision_rate_fail, "required_revised_metric_cells"].notna().any():
        failures.append("rate_breach_given_revision_sample_plan")

    if contract.get("weighted_score_used") is not False:
        failures.append("evidence_plan_weighted_score")
    if contract.get("budget_relaxed_for_planning") is not False:
        failures.append("evidence_plan_budget_relaxed")
    if int(contract.get("simultaneous_one_sided_bounds", -1)) != 72:
        failures.append("evidence_plan_bound_count")
    if abs(float(contract.get("per_bound_alpha", -1)) - 0.05 / 72.0) > 1e-15:
        failures.append("evidence_plan_alpha")

    if decision.get("weighted_score_used") is not False:
        failures.append("evidence_decision_weighted_score")
    if decision.get("budget_relaxed_for_planning") is not False:
        failures.append("evidence_decision_budget_relaxed")
    if eligible.empty:
        if decision.get("status") != "no_candidate_evidence_only_addressable":
            failures.append("evidence_decision_none_status")
    else:
        expected = float(eligible["allowed_lateness_hours"].min())
        if decision.get("status") != "selected":
            failures.append("evidence_decision_status")
        if float(decision.get("selected_lateness_hours", -1)) != expected:
            failures.append("evidence_decision_not_shortest")

    return failures


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate prospective watermark certification evidence plan")
    parser.add_argument("root", nargs="?", default="build/reference")
    args = parser.parse_args()
    failures = validate_evidence_plan(Path(args.root))
    if failures:
        raise SystemExit("Evidence-plan validation failed: " + ", ".join(failures))
    print(f"Evidence-plan validation passed: {args.root}")


if __name__ == "__main__":
    main()
