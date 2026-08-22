from __future__ import annotations

from dataclasses import asdict

import pandas as pd
from scipy.stats import beta

from .freshness import DEFAULT_WATERMARK_RISK_BUDGET, WatermarkRiskBudget


DEFAULT_FAMILY_ALPHA = 0.05
PROPORTION_CONSTRAINTS_PER_ROW = 2


def exact_binomial_upper(successes: int, trials: int, alpha: float) -> float:
    """One-sided Clopper-Pearson upper bound for a binomial proportion."""
    successes = int(successes)
    trials = int(trials)
    alpha = float(alpha)
    if trials <= 0:
        raise ValueError("trials must be positive")
    if successes < 0 or successes > trials:
        raise ValueError("successes must be between 0 and trials")
    if not 0 < alpha < 1:
        raise ValueError("alpha must be between 0 and 1")
    if successes == trials:
        return 1.0
    return float(beta.ppf(1.0 - alpha, successes + 1, trials - successes))


def watermark_uncertainty_grid(
    rolling_grid: pd.DataFrame,
    budget: WatermarkRiskBudget = DEFAULT_WATERMARK_RISK_BUDGET,
    family_alpha: float = DEFAULT_FAMILY_ALPHA,
) -> tuple[pd.DataFrame, dict[str, object]]:
    """Add simultaneous one-sided proportion bounds to the rolling grid.

    The Bonferroni family includes both proportion constraints for every
    candidate-window row used by the eventual policy selector. This is more
    conservative than treating the selected candidate as pre-specified.

    Revenue and paid-subscription maximum revisions remain deterministic hard
    gates. This function does not invent a sampling distribution for maxima.
    """
    required = {
        "window_index",
        "allowed_lateness_hours",
        "finalizable_events",
        "late_beyond_watermark_events",
        "late_event_fraction",
        "finalized_metric_cells",
        "revised_metric_cells",
        "revised_metric_cell_fraction",
        "max_abs_revenue_revision_gbp",
        "max_abs_paid_subscription_revision",
    }
    missing = required.difference(rolling_grid.columns)
    if missing:
        raise ValueError(f"rolling_grid missing columns: {sorted(missing)}")
    if rolling_grid.empty:
        raise ValueError("rolling_grid must be non-empty")
    if not 0 < family_alpha < 1:
        raise ValueError("family_alpha must be between 0 and 1")

    frame = rolling_grid.copy()
    simultaneous_bounds = int(len(frame) * PROPORTION_CONSTRAINTS_PER_ROW)
    per_bound_alpha = float(family_alpha / simultaneous_bounds)

    frame["late_event_fraction_upper"] = [
        exact_binomial_upper(x, n, per_bound_alpha)
        for x, n in zip(
            frame["late_beyond_watermark_events"],
            frame["finalizable_events"],
            strict=True,
        )
    ]
    frame["revised_metric_cell_fraction_upper"] = [
        exact_binomial_upper(x, n, per_bound_alpha)
        for x, n in zip(
            frame["revised_metric_cells"],
            frame["finalized_metric_cells"],
            strict=True,
        )
    ]

    frame["passes_late_event_upper"] = frame["late_event_fraction_upper"].le(
        budget.max_late_event_fraction
    )
    frame["passes_revised_metric_cell_upper"] = frame[
        "revised_metric_cell_fraction_upper"
    ].le(budget.max_revised_metric_cell_fraction)
    frame["passes_revenue_revision_hard_gate"] = frame[
        "max_abs_revenue_revision_gbp"
    ].le(budget.max_abs_revenue_revision_gbp)
    frame["passes_paid_subscription_revision_hard_gate"] = frame[
        "max_abs_paid_subscription_revision"
    ].le(budget.max_abs_paid_subscription_revision)
    frame["certified_under_binomial_model"] = (
        frame["passes_late_event_upper"]
        & frame["passes_revised_metric_cell_upper"]
        & frame["passes_revenue_revision_hard_gate"]
        & frame["passes_paid_subscription_revision_hard_gate"]
    )

    contract = {
        "version": "1.0",
        "family_alpha": float(family_alpha),
        "family_confidence_level": float(1.0 - family_alpha),
        "correction": "bonferroni",
        "candidate_window_rows": int(len(frame)),
        "proportion_constraints_per_row": PROPORTION_CONSTRAINTS_PER_ROW,
        "simultaneous_one_sided_bounds": simultaneous_bounds,
        "per_bound_alpha": per_bound_alpha,
        "proportion_bound": "one-sided Clopper-Pearson upper confidence bound",
        "selection_family_scope": "all candidate-window late-event and revised-cell proportions used by selection",
        "maximum_revision_policy": "revenue and paid-subscription maxima remain deterministic hard gates; no confidence interval is fabricated for maxima",
        "model_boundary": "binomial bounds treat event/cell indicators as Bernoulli observations; within-window batch or temporal clustering is not modelled",
        "overlapping_window_boundary": "Bonferroni family-wise control does not require independence across rolling windows, but the individual binomial model assumptions still matter",
        "budget": asdict(budget),
        "weighted_score_used": False,
    }
    return frame, contract


def watermark_uncertainty_summary(certification_grid: pd.DataFrame) -> pd.DataFrame:
    required = {
        "window_index",
        "allowed_lateness_hours",
        "feasible",
        "certified_under_binomial_model",
        "late_event_fraction",
        "late_event_fraction_upper",
        "revised_metric_cell_fraction",
        "revised_metric_cell_fraction_upper",
        "max_abs_revenue_revision_gbp",
        "max_abs_paid_subscription_revision",
    }
    missing = required.difference(certification_grid.columns)
    if missing:
        raise ValueError(f"certification_grid missing columns: {sorted(missing)}")

    frame = certification_grid.copy()
    frame["feasible"] = frame["feasible"].astype(bool)
    frame["certified_under_binomial_model"] = frame[
        "certified_under_binomial_model"
    ].astype(bool)
    out = (
        frame.groupby("allowed_lateness_hours", as_index=False)
        .agg(
            windows=("window_index", "nunique"),
            observed_feasible_windows=("feasible", "sum"),
            certified_windows=("certified_under_binomial_model", "sum"),
            max_late_event_fraction=("late_event_fraction", "max"),
            max_late_event_fraction_upper=("late_event_fraction_upper", "max"),
            max_revised_metric_cell_fraction=("revised_metric_cell_fraction", "max"),
            max_revised_metric_cell_fraction_upper=(
                "revised_metric_cell_fraction_upper",
                "max",
            ),
            max_abs_revenue_revision_gbp=("max_abs_revenue_revision_gbp", "max"),
            max_abs_paid_subscription_revision=(
                "max_abs_paid_subscription_revision",
                "max",
            ),
        )
    )
    out["observed_feasibility_rate"] = out["observed_feasible_windows"] / out["windows"]
    out["certification_rate"] = out["certified_windows"] / out["windows"]
    out["certified_all_windows"] = out["certified_windows"].eq(out["windows"])
    return out.sort_values("allowed_lateness_hours").reset_index(drop=True)


def select_certified_watermark_policy(
    certification_summary: pd.DataFrame,
    uncertainty_contract: dict[str, object],
) -> dict[str, object]:
    """Select the shortest all-window certified policy, or report none."""
    required = {
        "allowed_lateness_hours",
        "windows",
        "certified_windows",
        "certified_all_windows",
    }
    missing = required.difference(certification_summary.columns)
    if missing:
        raise ValueError(f"certification_summary missing columns: {sorted(missing)}")

    certified = certification_summary.loc[
        certification_summary["certified_all_windows"].astype(bool)
    ].sort_values("allowed_lateness_hours")
    selected = None if certified.empty else certified.iloc[0]
    return {
        "version": "1.0",
        "selection_rule": "shortest candidate whose simultaneous upper bounds and deterministic hard gates pass in every rolling window",
        "family_confidence_level": uncertainty_contract["family_confidence_level"],
        "correction": uncertainty_contract["correction"],
        "per_bound_alpha": uncertainty_contract["per_bound_alpha"],
        "weighted_score_used": False,
        "budget_relaxed_after_uncertainty": False,
        "status": "selected" if selected is not None else "no_candidate_certified_familywise_95",
        "selected_lateness_hours": None
        if selected is None
        else float(selected["allowed_lateness_hours"]),
        "selected_certification_rate": None
        if selected is None
        else float(selected["certification_rate"]),
        "operating_interpretation_if_none": "retain the observed-stability result as descriptive evidence, but do not label any candidate statistically certified under this model; collect more evidence or pre-specify a different risk budget rather than relaxing it post hoc",
    }
