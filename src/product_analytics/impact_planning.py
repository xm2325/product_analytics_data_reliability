from __future__ import annotations

from dataclasses import dataclass
from math import floor, sqrt
from typing import Mapping, Sequence

import pandas as pd
from scipy.stats import norm


DEFAULT_ELIGIBLE_USERS_PER_COHORT = (100_000, 100_000, 100_000)
DEFAULT_ADOPTION_SHARES = (0.25, 0.50, 0.75)
DEFAULT_PAID_HARM_GUARDRAIL = -0.03
DEFAULT_CONFIDENCE_LEVEL = 0.95


@dataclass(frozen=True)
class GuardrailEvidencePlan:
    observed_control_rate: float
    observed_treatment_rate: float
    observed_difference: float
    harm_margin: float
    confidence_level: float
    current_n_control: int
    current_n_treatment: int
    current_ci_low: float
    current_guardrail_passes: bool
    equal_allocation_target_per_arm: int | None
    additional_users_per_arm_from_current_minimum: int | None
    status: str
    interpretation: str


@dataclass(frozen=True)
class ImpactDecisionSummary:
    experiment_action: str
    planning_status: str
    decision_authorised_rollout: bool
    counterfactual_treated_users: int
    counterfactual_incremental_revenue_gbp: float
    counterfactual_incremental_revenue_ci_low_gbp: float
    counterfactual_incremental_revenue_ci_high_gbp: float
    authorised_treated_users: int
    authorised_incremental_revenue_gbp: float | None
    interpretation: str


def impact_planning_contract() -> dict[str, object]:
    return {
        "version": "1.0",
        "planning_horizon_calendar_days": 90,
        "metric_horizon_per_cohort_days": 30,
        "eligible_users_per_cohort": list(DEFAULT_ELIGIBLE_USERS_PER_COHORT),
        "hypothetical_adoption_shares": list(DEFAULT_ADOPTION_SHARES),
        "revenue_effect_source": "pricing experiment ANCOVA treatment effect and its 95% confidence interval",
        "uncertainty_propagation": "fixed planned treated-user counts multiplied by the experiment effect confidence interval",
        "guardrail_evidence_rule": "minimum equal-allocation per-arm sample size whose projected difference-in-proportions lower confidence bound clears the pre-specified non-inferiority margin, conditioning on observed arm rates and retaining the experiment's ddof=1 variance convention",
        "guardrail_harm_margin": DEFAULT_PAID_HARM_GUARDRAIL,
        "confidence_level": DEFAULT_CONFIDENCE_LEVEL,
        "hold_policy": "HOLD or INVALID experiments may have counterfactual impact scenarios but no decision-authorised rollout impact",
        "no_ltv_extrapolation": True,
        "no_effect_persistence_beyond_30d_assumed": True,
        "synthetic_scale_only": True,
    }


def _binary_series(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame.columns:
        raise ValueError(f"Missing binary column: {column}")
    values = pd.to_numeric(frame[column], errors="raise")
    if values.isna().any() or not values.isin([0, 1]).all():
        raise ValueError(f"{column} must contain non-missing binary 0/1 values")
    return values.astype(int)


def _projected_equal_arm_lower_bound(
    p_control: float,
    p_treatment: float,
    n_per_arm: int,
    z: float,
) -> float:
    if n_per_arm < 2:
        raise ValueError("n_per_arm must be at least 2")
    # The experiment's difference_in_means uses sample variance with ddof=1.
    # For a Bernoulli arm with fixed planning rate p and arm size n,
    # sample_variance / n = p(1-p)/(n-1).
    variance_sum = p_control * (1.0 - p_control) + p_treatment * (1.0 - p_treatment)
    return (p_treatment - p_control) - z * sqrt(variance_sum / (n_per_arm - 1))


def guardrail_evidence_plan(
    frame: pd.DataFrame,
    *,
    outcome: str = "paid_subscription_30d",
    treatment: str = "treatment",
    harm_margin: float = DEFAULT_PAID_HARM_GUARDRAIL,
    confidence_level: float = DEFAULT_CONFIDENCE_LEVEL,
) -> GuardrailEvidencePlan:
    """Plan equal-allocation evidence needed to clear a non-inferiority guardrail.

    This is conditional evidence planning, not a power guarantee: observed arm rates
    are treated as fixed planning rates and the same ddof=1 normal confidence-bound
    convention used by the experiment guardrail is projected to larger equal arms.
    """
    if not 0 < confidence_level < 1:
        raise ValueError("confidence_level must be between 0 and 1")
    assignment = _binary_series(frame, treatment)
    response = _binary_series(frame, outcome)
    control = response.loc[assignment.eq(0)]
    treated = response.loc[assignment.eq(1)]
    if len(control) < 2 or len(treated) < 2:
        raise ValueError("Need at least two observations per arm")

    p_control = float(control.mean())
    p_treatment = float(treated.mean())
    difference = p_treatment - p_control
    z = float(norm.ppf(0.5 + confidence_level / 2.0))
    current_se = sqrt(float(control.var(ddof=1) / len(control) + treated.var(ddof=1) / len(treated)))
    current_ci_low = difference - z * current_se
    current_passes = current_ci_low > harm_margin

    if difference <= harm_margin:
        target = None
        additional = None
        status = "structural_point_estimate_failure"
        interpretation = (
            "observed treatment-control conversion difference is at or below the harm margin; "
            "more sample alone cannot clear the guardrail if the planning rates stay unchanged"
        )
    else:
        variance_sum = p_control * (1.0 - p_control) + p_treatment * (1.0 - p_treatment)
        slack = difference - harm_margin
        threshold_n_minus_one = (z * z * variance_sum) / (slack * slack)
        target = max(2, floor(threshold_n_minus_one) + 2)
        # Strictly audit both sides of the integer boundary against the projected rule.
        while _projected_equal_arm_lower_bound(p_control, p_treatment, target, z) <= harm_margin:
            target += 1
        while target > 2 and _projected_equal_arm_lower_bound(p_control, p_treatment, target - 1, z) > harm_margin:
            target -= 1
        additional = max(0, target - min(len(control), len(treated)))
        status = "already_clears_under_observed_rates" if current_passes else "additional_evidence_required"
        interpretation = (
            "conditional equal-allocation target under observed conversion rates; it is not a guarantee that "
            "future data will preserve the same treatment effect or variance"
        )

    return GuardrailEvidencePlan(
        observed_control_rate=p_control,
        observed_treatment_rate=p_treatment,
        observed_difference=difference,
        harm_margin=float(harm_margin),
        confidence_level=float(confidence_level),
        current_n_control=int(len(control)),
        current_n_treatment=int(len(treated)),
        current_ci_low=float(current_ci_low),
        current_guardrail_passes=bool(current_passes),
        equal_allocation_target_per_arm=target,
        additional_users_per_arm_from_current_minimum=additional,
        status=status,
        interpretation=interpretation,
    )


def rollout_impact_scenario(
    revenue_estimate: Mapping[str, float],
    *,
    eligible_users_per_cohort: Sequence[int] = DEFAULT_ELIGIBLE_USERS_PER_COHORT,
    adoption_shares: Sequence[float] = DEFAULT_ADOPTION_SHARES,
) -> pd.DataFrame:
    """Translate a 30-day per-user effect into fixed-volume launch-cohort scenarios."""
    if len(eligible_users_per_cohort) == 0 or len(eligible_users_per_cohort) != len(adoption_shares):
        raise ValueError("eligible_users_per_cohort and adoption_shares must be non-empty and equal length")
    required = {"effect", "ci_low", "ci_high"}
    missing = required.difference(revenue_estimate)
    if missing:
        raise ValueError(f"Missing revenue estimate fields: {sorted(missing)}")

    effect = float(revenue_estimate["effect"])
    ci_low = float(revenue_estimate["ci_low"])
    ci_high = float(revenue_estimate["ci_high"])
    if not ci_low <= effect <= ci_high:
        raise ValueError("Revenue effect must lie inside its confidence interval")

    rows: list[dict[str, object]] = []
    for index, (eligible, share) in enumerate(zip(eligible_users_per_cohort, adoption_shares, strict=True), start=1):
        if int(eligible) != eligible or eligible <= 0:
            raise ValueError("eligible user counts must be positive integers")
        if not 0.0 <= float(share) <= 1.0:
            raise ValueError("adoption shares must be between 0 and 1")
        treated = int(round(int(eligible) * float(share)))
        rows.append(
            {
                "cohort_index": index,
                "eligible_users": int(eligible),
                "hypothetical_adoption_share": float(share),
                "hypothetical_treated_users": treated,
                "revenue_effect_gbp_per_user_30d": effect,
                "revenue_effect_ci_low_gbp_per_user_30d": ci_low,
                "revenue_effect_ci_high_gbp_per_user_30d": ci_high,
                "counterfactual_incremental_revenue_gbp": treated * effect,
                "counterfactual_incremental_revenue_ci_low_gbp": treated * ci_low,
                "counterfactual_incremental_revenue_ci_high_gbp": treated * ci_high,
            }
        )
    return pd.DataFrame(rows)


def summarise_impact_decision(
    scenario: pd.DataFrame,
    experiment_decision: Mapping[str, object],
) -> ImpactDecisionSummary:
    if scenario.empty:
        raise ValueError("scenario must be non-empty")
    action = str(experiment_decision.get("action", ""))
    if action not in {"rollout", "hold", "invalid"}:
        raise ValueError("experiment decision action must be rollout, hold or invalid")

    treated = int(scenario["hypothetical_treated_users"].sum())
    expected = float(scenario["counterfactual_incremental_revenue_gbp"].sum())
    ci_low = float(scenario["counterfactual_incremental_revenue_ci_low_gbp"].sum())
    ci_high = float(scenario["counterfactual_incremental_revenue_ci_high_gbp"].sum())

    authorised = action == "rollout"
    if authorised:
        planning_status = "decision_authorised"
        authorised_users = treated
        authorised_revenue = expected
        interpretation = "experiment gates pass; the fixed-volume launch scenario is decision-authorised planning evidence"
    elif action == "hold":
        planning_status = "counterfactual_only"
        authorised_users = 0
        authorised_revenue = None
        interpretation = (
            "experiment is HOLD; positive counterfactual revenue cannot be represented as authorised rollout impact "
            "until the failed guardrail is resolved"
        )
    else:
        planning_status = "invalid_experiment_no_rollout"
        authorised_users = 0
        authorised_revenue = None
        interpretation = "experiment is INVALID; effect estimates must not authorise rollout planning"

    return ImpactDecisionSummary(
        experiment_action=action,
        planning_status=planning_status,
        decision_authorised_rollout=authorised,
        counterfactual_treated_users=treated,
        counterfactual_incremental_revenue_gbp=expected,
        counterfactual_incremental_revenue_ci_low_gbp=ci_low,
        counterfactual_incremental_revenue_ci_high_gbp=ci_high,
        authorised_treated_users=authorised_users,
        authorised_incremental_revenue_gbp=authorised_revenue,
        interpretation=interpretation,
    )


def build_impact_plan(
    experiment_users: pd.DataFrame,
    experiment_estimates: pd.DataFrame,
    experiment_decision: Mapping[str, object],
) -> tuple[pd.DataFrame, GuardrailEvidencePlan, ImpactDecisionSummary, dict[str, object]]:
    revenue_rows = experiment_estimates.loc[experiment_estimates["metric"].eq("revenue_gbp_30d")]
    if len(revenue_rows) != 1:
        raise ValueError("Expected exactly one revenue_gbp_30d estimate")
    scenario = rollout_impact_scenario(revenue_rows.iloc[0].to_dict())
    evidence = guardrail_evidence_plan(experiment_users)
    summary = summarise_impact_decision(scenario, experiment_decision)
    return scenario, evidence, summary, impact_planning_contract()
