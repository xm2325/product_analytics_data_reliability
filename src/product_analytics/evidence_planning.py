from __future__ import annotations

from dataclasses import asdict
from math import ceil

import pandas as pd

from .freshness import DEFAULT_WATERMARK_RISK_BUDGET, WatermarkRiskBudget
from .uncertainty import DEFAULT_FAMILY_ALPHA, exact_binomial_upper


DEFAULT_MAX_PLANNING_TRIALS = 100_000_000


def _planned_successes(rate: float, trials: int) -> int:
    """Conservative integer count for a planning rate."""
    if not 0 <= rate <= 1:
        raise ValueError("rate must be between 0 and 1")
    return min(int(trials), int(ceil(float(rate) * int(trials))))


def required_trials_for_exact_upper(
    planning_rate: float,
    limit: float,
    alpha: float,
    *,
    max_trials: int = DEFAULT_MAX_PLANNING_TRIALS,
) -> int | None:
    """Find a conservative evidence size for a one-sided exact upper bound.

    The planning count is ceil(planning_rate * n), so the calculation does not
    rely on rounding a favourable fractional expected count downward. If the
    planning rate is already at or above the risk limit, more evidence cannot
    solve the point-estimate problem and the function returns None.

    A None result can therefore mean either the planning rate itself is not
    below the limit or no passing sample size was found up to max_trials. The
    higher-level plan records those cases separately.
    """
    planning_rate = float(planning_rate)
    limit = float(limit)
    alpha = float(alpha)
    max_trials = int(max_trials)
    if not 0 <= planning_rate <= 1:
        raise ValueError("planning_rate must be between 0 and 1")
    if not 0 < limit < 1:
        raise ValueError("limit must be between 0 and 1")
    if not 0 < alpha < 1:
        raise ValueError("alpha must be between 0 and 1")
    if max_trials <= 0:
        raise ValueError("max_trials must be positive")
    if planning_rate >= limit:
        return None

    def passes(n: int) -> bool:
        x = _planned_successes(planning_rate, n)
        return exact_binomial_upper(x, n, alpha) <= limit

    lo = 1
    hi = 1
    while hi < max_trials and not passes(hi):
        lo = hi
        hi = min(max_trials, hi * 2)
    if not passes(hi):
        return None

    left, right = lo, hi
    while left + 1 < right:
        mid = (left + right) // 2
        if passes(mid):
            right = mid
        else:
            left = mid

    # ceil(p*n) introduces small saw-tooth jumps. Scan a neighbourhood around
    # the apparent crossing so the reported threshold is not a binary artefact.
    period = int(ceil(1.0 / planning_rate)) if planning_rate > 0 else 1
    scan_start = max(1, right - max(5000, 4 * period))
    for n in range(scan_start, right + 1):
        if passes(n):
            return n
    return right


def certification_evidence_plan(
    rolling_grid: pd.DataFrame,
    *,
    family_alpha: float = DEFAULT_FAMILY_ALPHA,
    budget: WatermarkRiskBudget = DEFAULT_WATERMARK_RISK_BUDGET,
    max_planning_trials: int = DEFAULT_MAX_PLANNING_TRIALS,
) -> tuple[pd.DataFrame, dict[str, object]]:
    """Plan evidence depth without changing the certification budget.

    For each candidate, use the worst observed rolling-window proportional rate
    as a prospective planning rate. A candidate is evidence-only addressable
    only when both planning rates are below their limits, both deterministic
    maximum-revision gates pass, and both exact evidence requirements are
    quantifiable inside the declared search cap.
    """
    required = {
        "window_index",
        "allowed_lateness_hours",
        "late_event_fraction",
        "revised_metric_cell_fraction",
        "max_abs_revenue_revision_gbp",
        "max_abs_paid_subscription_revision",
        "finalizable_events",
        "finalized_metric_cells",
        "finalized_calendar_dates",
    }
    missing = required.difference(rolling_grid.columns)
    if missing:
        raise ValueError(f"rolling_grid missing columns: {sorted(missing)}")
    if rolling_grid.empty:
        raise ValueError("rolling_grid must be non-empty")
    if int(max_planning_trials) <= 0:
        raise ValueError("max_planning_trials must be positive")

    candidate_count = int(rolling_grid["allowed_lateness_hours"].nunique())
    window_count = int(rolling_grid["window_index"].nunique())
    simultaneous_bounds = candidate_count * window_count * 2
    per_bound_alpha = float(family_alpha / simultaneous_bounds)

    rows: list[dict[str, object]] = []
    for hours, part in rolling_grid.groupby("allowed_lateness_hours", sort=True):
        late_rate = float(part["late_event_fraction"].max())
        revision_rate = float(part["revised_metric_cell_fraction"].max())
        max_revenue = float(part["max_abs_revenue_revision_gbp"].max())
        max_paid = float(part["max_abs_paid_subscription_revision"].max())

        late_rate_below = late_rate < budget.max_late_event_fraction
        revision_rate_below = revision_rate < budget.max_revised_metric_cell_fraction
        revenue_gate = max_revenue <= budget.max_abs_revenue_revision_gbp
        paid_gate = max_paid <= budget.max_abs_paid_subscription_revision

        late_n = (
            required_trials_for_exact_upper(
                late_rate,
                budget.max_late_event_fraction,
                per_bound_alpha,
                max_trials=max_planning_trials,
            )
            if late_rate_below
            else None
        )
        revision_n = (
            required_trials_for_exact_upper(
                revision_rate,
                budget.max_revised_metric_cell_fraction,
                per_bound_alpha,
                max_trials=max_planning_trials,
            )
            if revision_rate_below
            else None
        )
        late_cap_exceeded = bool(late_rate_below and late_n is None)
        revision_cap_exceeded = bool(revision_rate_below and revision_n is None)
        evidence_requirement_quantified = bool(late_n is not None and revision_n is not None)

        finalizable_per_day = (
            part["finalizable_events"] / part["finalized_calendar_dates"].replace(0, pd.NA)
        ).dropna()
        metric_cells_per_day = (
            part["finalized_metric_cells"] / part["finalized_calendar_dates"].replace(0, pd.NA)
        ).dropna()
        median_event_throughput = float(finalizable_per_day.median())
        median_metric_throughput = float(metric_cells_per_day.median())

        late_days = None if late_n is None else int(ceil(late_n / median_event_throughput))
        revision_days = None if revision_n is None else int(ceil(revision_n / median_metric_throughput))
        evidence_days = None
        evidence_years = None
        if late_days is not None and revision_days is not None:
            evidence_days = max(late_days, revision_days)
            evidence_years = evidence_days / 365.25

        reasons: list[str] = []
        if not late_rate_below:
            reasons.append("worst observed late-event rate is at/above budget")
        if not revision_rate_below:
            reasons.append("worst observed revised-cell rate is at/above budget")
        if not revenue_gate:
            reasons.append("observed revenue-revision hard gate breaches")
        if not paid_gate:
            reasons.append("observed paid-subscription hard gate breaches")
        if late_cap_exceeded:
            reasons.append(f"late-event evidence requirement exceeds {int(max_planning_trials):,}-trial search cap")
        if revision_cap_exceeded:
            reasons.append(f"revised-cell evidence requirement exceeds {int(max_planning_trials):,}-trial search cap")

        evidence_only_addressable = bool(
            late_rate_below
            and revision_rate_below
            and revenue_gate
            and paid_gate
            and evidence_requirement_quantified
        )
        if evidence_only_addressable:
            reasons.append(
                "point risks and deterministic maxima pass; certification gap is evidence depth under the stated planning rates"
            )

        rows.append(
            {
                "allowed_lateness_hours": float(hours),
                "planning_late_event_rate": late_rate,
                "planning_revised_metric_cell_rate": revision_rate,
                "max_abs_revenue_revision_gbp": max_revenue,
                "max_abs_paid_subscription_revision": max_paid,
                "late_rate_below_budget": bool(late_rate_below),
                "revised_rate_below_budget": bool(revision_rate_below),
                "revenue_hard_gate_passes": bool(revenue_gate),
                "paid_hard_gate_passes": bool(paid_gate),
                "required_late_event_trials": late_n,
                "required_revised_metric_cells": revision_n,
                "late_trial_requirement_exceeds_search_cap": late_cap_exceeded,
                "revision_trial_requirement_exceeds_search_cap": revision_cap_exceeded,
                "evidence_requirement_quantified": evidence_requirement_quantified,
                "median_finalizable_events_per_day": median_event_throughput,
                "median_metric_cells_per_day": median_metric_throughput,
                "estimated_calendar_days_for_late_bound": late_days,
                "estimated_calendar_days_for_revision_bound": revision_days,
                "estimated_calendar_days_for_both_proportions": evidence_days,
                "estimated_calendar_years_for_both_proportions": evidence_years,
                "evidence_only_addressable": evidence_only_addressable,
                "planning_interpretation": "; ".join(reasons),
            }
        )

    contract = {
        "version": "1.1",
        "planning_rule": "use each candidate's worst observed rolling-window proportional rate; keep the v0.29 family-wise alpha allocation and original hard risk budget unchanged",
        "success_count_rule": "ceil(planning_rate * trials)",
        "family_alpha": float(family_alpha),
        "candidate_count": candidate_count,
        "window_count": window_count,
        "simultaneous_one_sided_bounds": simultaneous_bounds,
        "per_bound_alpha": per_bound_alpha,
        "proportion_bound": "one-sided Clopper-Pearson upper confidence bound",
        "max_planning_trials": int(max_planning_trials),
        "throughput_rule": "convert required trials to approximate calendar evidence depth using median observed candidate-specific evidence throughput",
        "calendar_day_interpretation": "reported days are total prospective evidence depth under the stated planning rates and throughput, not a guarantee that waiting that many additional wall-clock days will certify the policy",
        "deterministic_gate_rule": "more proportional evidence cannot repair an already-breached revenue or paid-subscription maximum-revision hard gate",
        "rate_gate_rule": "if the worst observed planning rate is at or above its budget, more sample alone cannot make the asymptotic upper bound fall below that budget",
        "search_cap_rule": "if a planning rate is below budget but no passing exact bound is found by max_planning_trials, report the requirement as above the search cap rather than as a structural rate breach",
        "planning_boundary": "sample-size calculations condition on future risk rates and evidence throughput remaining at the stated planning values; they are not guarantees of future certification",
        "budget": asdict(budget),
        "weighted_score_used": False,
        "budget_relaxed_for_planning": False,
    }
    return pd.DataFrame(rows), contract


def select_evidence_plan(plan: pd.DataFrame) -> dict[str, object]:
    """Identify the shortest candidate whose certification gap is evidence-only."""
    required = {
        "allowed_lateness_hours",
        "evidence_only_addressable",
        "estimated_calendar_days_for_both_proportions",
        "estimated_calendar_years_for_both_proportions",
    }
    missing = required.difference(plan.columns)
    if missing:
        raise ValueError(f"plan missing columns: {sorted(missing)}")
    eligible = plan.loc[plan["evidence_only_addressable"].astype(bool)].sort_values(
        "allowed_lateness_hours"
    )
    selected = None if eligible.empty else eligible.iloc[0]
    return {
        "version": "1.1",
        "selection_rule": "shortest candidate whose current certification gap can be addressed by additional proportional evidence alone under the unchanged hard gates",
        "weighted_score_used": False,
        "budget_relaxed_for_planning": False,
        "status": "selected" if selected is not None else "no_candidate_evidence_only_addressable",
        "selected_lateness_hours": None if selected is None else float(selected["allowed_lateness_hours"]),
        "estimated_calendar_days_for_both_proportions": None
        if selected is None
        else int(selected["estimated_calendar_days_for_both_proportions"]),
        "estimated_calendar_years_for_both_proportions": None
        if selected is None
        else float(selected["estimated_calendar_years_for_both_proportions"]),
        "interpretation": None if selected is None else str(selected["planning_interpretation"]),
    }
