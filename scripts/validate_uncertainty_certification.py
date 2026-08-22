from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd


REQUIRED_ARTIFACTS = {
    "watermark_uncertainty_grid.csv",
    "watermark_uncertainty_summary.csv",
    "watermark_uncertainty_contract.json",
    "watermark_certification_decision.json",
}


def _as_bool(values: pd.Series) -> pd.Series:
    return values.astype(str).str.lower().eq("true")


def validate_uncertainty_certification(root: Path) -> list[str]:
    failures: list[str] = []
    missing = sorted(name for name in REQUIRED_ARTIFACTS if not (root / name).is_file())
    if missing:
        return [f"missing:{name}" for name in missing]

    grid = pd.read_csv(root / "watermark_uncertainty_grid.csv")
    summary = pd.read_csv(root / "watermark_uncertainty_summary.csv").sort_values(
        "allowed_lateness_hours"
    )
    contract = json.loads((root / "watermark_uncertainty_contract.json").read_text(encoding="utf-8"))
    decision = json.loads((root / "watermark_certification_decision.json").read_text(encoding="utf-8"))

    required_grid = {
        "window_index",
        "allowed_lateness_hours",
        "late_event_fraction",
        "late_event_fraction_upper",
        "revised_metric_cell_fraction",
        "revised_metric_cell_fraction_upper",
        "passes_late_event_upper",
        "passes_revised_metric_cell_upper",
        "passes_revenue_revision_hard_gate",
        "passes_paid_subscription_revision_hard_gate",
        "certified_under_binomial_model",
        "feasible",
    }
    if not required_grid.issubset(grid.columns):
        failures.append("uncertainty_grid_columns")
        return failures

    if not (grid["late_event_fraction_upper"] >= grid["late_event_fraction"] - 1e-15).all():
        failures.append("late_upper_below_point")
    if not (
        grid["revised_metric_cell_fraction_upper"]
        >= grid["revised_metric_cell_fraction"] - 1e-15
    ).all():
        failures.append("revision_upper_below_point")
    if not grid["late_event_fraction_upper"].between(0, 1).all():
        failures.append("late_upper_bounds")
    if not grid["revised_metric_cell_fraction_upper"].between(0, 1).all():
        failures.append("revision_upper_bounds")

    certified = _as_bool(grid["certified_under_binomial_model"])
    component_pass = (
        _as_bool(grid["passes_late_event_upper"])
        & _as_bool(grid["passes_revised_metric_cell_upper"])
        & _as_bool(grid["passes_revenue_revision_hard_gate"])
        & _as_bool(grid["passes_paid_subscription_revision_hard_gate"])
    )
    if not certified.eq(component_pass).all():
        failures.append("certification_component_accounting")
    if (certified & ~_as_bool(grid["feasible"])).any():
        failures.append("certified_without_observed_feasibility")

    expected_bounds = len(grid) * 2
    if int(contract.get("simultaneous_one_sided_bounds", -1)) != expected_bounds:
        failures.append("simultaneous_bound_count")
    if int(contract.get("proportion_constraints_per_row", -1)) != 2:
        failures.append("proportion_constraint_count")
    family_alpha = float(contract.get("family_alpha", -1))
    per_bound_alpha = float(contract.get("per_bound_alpha", -1))
    if not 0 < family_alpha < 1:
        failures.append("family_alpha")
    elif abs(per_bound_alpha - family_alpha / expected_bounds) > 1e-15:
        failures.append("bonferroni_alpha_accounting")
    if contract.get("correction") != "bonferroni":
        failures.append("correction")
    if contract.get("weighted_score_used") is not False:
        failures.append("uncertainty_weighted_score")
    if "deterministic hard gates" not in contract.get("maximum_revision_policy", ""):
        failures.append("max_revision_policy")

    window_count = int(grid["window_index"].nunique())
    candidates = set(grid["allowed_lateness_hours"].astype(float))
    if len(grid) != window_count * len(candidates):
        failures.append("uncertainty_grid_rectangularity")
    if set(summary["allowed_lateness_hours"].astype(float)) != candidates:
        failures.append("uncertainty_summary_candidates")
    if not summary["windows"].eq(window_count).all():
        failures.append("uncertainty_summary_window_count")
    if not (summary["certified_windows"] <= summary["observed_feasible_windows"]).all():
        failures.append("certified_windows_exceed_observed")
    expected_rate = summary["certified_windows"] / summary["windows"]
    if not (summary["certification_rate"] - expected_rate).abs().lt(1e-12).all():
        failures.append("certification_rate_accounting")
    certified_all = _as_bool(summary["certified_all_windows"])
    if not certified_all.eq(summary["certified_windows"].eq(summary["windows"])).all():
        failures.append("certified_all_flag")

    if decision.get("weighted_score_used") is not False:
        failures.append("decision_weighted_score")
    if decision.get("budget_relaxed_after_uncertainty") is not False:
        failures.append("decision_budget_relaxed")
    eligible = summary.loc[certified_all]
    if eligible.empty:
        if decision.get("status") != "no_candidate_certified_familywise_95":
            failures.append("no_certified_candidate_status")
        if decision.get("selected_lateness_hours") is not None:
            failures.append("unexpected_certified_selection")
    else:
        expected = float(eligible["allowed_lateness_hours"].min())
        if decision.get("status") != "selected":
            failures.append("certified_selection_status")
        if float(decision.get("selected_lateness_hours", -1)) != expected:
            failures.append("certified_not_shortest")

    return failures


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate uncertainty-aware watermark certification")
    parser.add_argument("root", nargs="?", default="build/reference")
    args = parser.parse_args()
    failures = validate_uncertainty_certification(Path(args.root))
    if failures:
        raise SystemExit("Uncertainty-certification validation failed: " + ", ".join(failures))
    print(f"Uncertainty-certification validation passed: {args.root}")


if __name__ == "__main__":
    main()
