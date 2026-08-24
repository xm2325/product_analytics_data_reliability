from __future__ import annotations

from dataclasses import asdict, dataclass
from math import sqrt

import numpy as np
import pandas as pd
import statsmodels.api as sm
from scipy.stats import binomtest, norm


DEFAULT_SRM_ALPHA = 0.001
DEFAULT_PAID_HARM_GUARDRAIL = -0.03
DEFAULT_CONFIDENCE_LEVEL = 0.95


@dataclass(frozen=True)
class EffectEstimate:
    effect: float
    se: float
    ci_low: float
    ci_high: float
    n_control: int
    n_treatment: int


@dataclass(frozen=True)
class AssignmentIntegrity:
    n_total: int
    n_control: int
    n_treatment: int
    expected_treatment_share: float
    observed_treatment_share: float
    p_value: float
    alpha: float
    passes: bool


@dataclass(frozen=True)
class PricingDecision:
    action: str
    assignment_integrity_gate: bool
    revenue_gate: bool
    paid_guardrail_gate: bool
    reason: str


def _validate_binary_treatment(frame: pd.DataFrame, treatment: str) -> pd.Series:
    if treatment not in frame.columns:
        raise ValueError(f"Missing treatment column: {treatment}")
    values = pd.to_numeric(frame[treatment], errors="raise")
    if values.isna().any():
        raise ValueError("Treatment assignment cannot contain missing values")
    if not values.isin([0, 1]).all():
        raise ValueError("Treatment assignment must be binary 0/1")
    return values.astype(int)


def assignment_integrity(
    frame: pd.DataFrame,
    treatment: str = "treatment",
    *,
    expected_treatment_share: float = 0.5,
    alpha: float = DEFAULT_SRM_ALPHA,
) -> AssignmentIntegrity:
    """Exact two-sided sample-ratio-mismatch check for a binary experiment."""
    if not 0 < expected_treatment_share < 1:
        raise ValueError("expected_treatment_share must be between 0 and 1")
    if not 0 < alpha < 1:
        raise ValueError("alpha must be between 0 and 1")
    assignment = _validate_binary_treatment(frame, treatment)
    n_total = int(len(assignment))
    if n_total == 0:
        raise ValueError("Experiment frame must be non-empty")
    n_treatment = int(assignment.sum())
    n_control = n_total - n_treatment
    result = binomtest(n_treatment, n_total, p=expected_treatment_share, alternative="two-sided")
    p_value = float(result.pvalue)
    return AssignmentIntegrity(
        n_total=n_total,
        n_control=n_control,
        n_treatment=n_treatment,
        expected_treatment_share=float(expected_treatment_share),
        observed_treatment_share=float(n_treatment / n_total),
        p_value=p_value,
        alpha=float(alpha),
        passes=bool(p_value >= alpha),
    )


def difference_in_means(frame: pd.DataFrame, outcome: str, treatment: str = "treatment") -> EffectEstimate:
    assignment = _validate_binary_treatment(frame, treatment)
    if outcome not in frame.columns:
        raise ValueError(f"Missing outcome column: {outcome}")
    values = pd.to_numeric(frame[outcome], errors="raise")
    if values.isna().any():
        raise ValueError(f"{outcome} cannot contain missing values")
    control = values.loc[assignment.eq(0)].astype(float)
    treated = values.loc[assignment.eq(1)].astype(float)
    if len(control) < 2 or len(treated) < 2:
        raise ValueError("Need at least two observations per arm")
    effect = float(treated.mean() - control.mean())
    se = sqrt(float(treated.var(ddof=1) / len(treated) + control.var(ddof=1) / len(control)))
    z = float(norm.ppf(0.975))
    return EffectEstimate(effect, se, effect - z * se, effect + z * se, len(control), len(treated))


def difference_in_proportions(frame: pd.DataFrame, outcome: str, treatment: str = "treatment") -> EffectEstimate:
    if outcome not in frame.columns:
        raise ValueError(f"Missing outcome column: {outcome}")
    values = pd.to_numeric(frame[outcome], errors="raise")
    if values.isna().any() or not values.isin([0.0, 1.0]).all():
        raise ValueError(f"{outcome} must contain non-missing binary 0/1 values")
    return difference_in_means(frame, outcome=outcome, treatment=treatment)


def covariate_adjusted_effect(
    frame: pd.DataFrame,
    outcome: str,
    covariate: str,
    treatment: str = "treatment",
) -> EffectEstimate:
    """ANCOVA treatment effect with HC3 heteroskedasticity-robust uncertainty."""
    assignment = _validate_binary_treatment(frame, treatment)
    required = frame[[outcome, covariate]].astype(float)
    if required.isna().any().any():
        raise ValueError("Outcome and pre-period covariate cannot contain missing values")
    if required[covariate].nunique() < 2:
        raise ValueError("Pre-period covariate must vary")

    design = pd.DataFrame(
        {
            "treatment": assignment.astype(float),
            "pre_period": required[covariate],
        },
        index=frame.index,
    )
    fit = sm.OLS(required[outcome], sm.add_constant(design, has_constant="add")).fit(cov_type="HC3")
    effect = float(fit.params["treatment"])
    se = float(fit.bse["treatment"])
    z = float(norm.ppf(0.975))
    n_control = int((assignment == 0).sum())
    n_treatment = int((assignment == 1).sum())
    return EffectEstimate(effect, se, effect - z * se, effect + z * se, n_control, n_treatment)


def pricing_decision(
    revenue_effect: EffectEstimate,
    paid_effect: EffectEstimate,
    paid_harm_guardrail: float = DEFAULT_PAID_HARM_GUARDRAIL,
    *,
    integrity: AssignmentIntegrity | None = None,
) -> PricingDecision:
    """Use non-compensatory gates for experiment validity, revenue and paid conversion."""
    assignment_gate = True if integrity is None else bool(integrity.passes)
    revenue_gate = revenue_effect.ci_low > 0.0
    paid_gate = paid_effect.ci_low > paid_harm_guardrail

    if not assignment_gate:
        action = "invalid"
        reason = "sample-ratio-mismatch gate failed; do not use treatment-effect estimates for rollout"
    elif revenue_gate and paid_gate:
        action = "rollout"
        reason = "revenue lower confidence bound is positive and paid-conversion non-inferiority guardrail passes"
    else:
        action = "hold"
        failures = []
        if not revenue_gate:
            failures.append("revenue evidence is not decisively positive")
        if not paid_gate:
            failures.append("paid-conversion lower confidence bound crosses the harm guardrail")
        reason = "; ".join(failures)

    return PricingDecision(action, assignment_gate, revenue_gate, paid_gate, reason)


def pricing_experiment_contract() -> dict[str, object]:
    return {
        "version": "1.0",
        "primary_metric": "revenue_gbp_30d",
        "primary_analysis": "ANCOVA with pre-period revenue covariate and HC3 robust standard errors",
        "primary_gate": "95% two-sided confidence-interval lower bound for treatment revenue effect > 0",
        "guardrail_metric": "paid_subscription_30d",
        "guardrail_analysis": "difference in proportions with 95% two-sided normal confidence interval",
        "paid_harm_guardrail": DEFAULT_PAID_HARM_GUARDRAIL,
        "paid_guardrail_gate": "lower confidence bound for treatment-control paid-conversion difference > -0.03",
        "assignment_integrity": "exact two-sided binomial sample-ratio-mismatch test",
        "assignment_expected_treatment_share": 0.5,
        "assignment_alpha": DEFAULT_SRM_ALPHA,
        "confidence_level": DEFAULT_CONFIDENCE_LEVEL,
        "weighted_score_used": False,
        "revenue_cannot_compensate_for_guardrail_failure": True,
        "invalid_assignment_action": "invalidate experiment decision rather than reinterpret effect estimates",
    }


def generate_pricing_experiment(seed: int = 2206, n_per_arm: int = 4000) -> pd.DataFrame:
    """Generate a deterministic controlled pricing experiment for decision validation.

    The reference is intentionally configured so the revenue primary metric is
    positive while paid conversion remains statistically unable to clear the
    -3 percentage-point non-inferiority guardrail. The correct action is HOLD.
    """
    if n_per_arm < 2:
        raise ValueError("n_per_arm must be at least 2")
    rng = np.random.default_rng(seed)
    n_total = 2 * int(n_per_arm)
    treatment = np.concatenate(
        [np.zeros(n_per_arm, dtype=int), np.ones(n_per_arm, dtype=int)]
    )
    rng.shuffle(treatment)

    pre_revenue = rng.gamma(shape=2.2, scale=3.0, size=n_total)
    revenue = np.clip(
        1.5
        + 0.75 * pre_revenue
        + 0.75 * treatment
        + rng.normal(loc=0.0, scale=3.2, size=n_total),
        0.0,
        None,
    )
    paid_probability = np.where(treatment == 1, 0.192, 0.20)
    paid = rng.binomial(1, paid_probability, size=n_total)

    return pd.DataFrame(
        {
            "experiment_user_id": [f"pricing_{i:05d}" for i in range(n_total)],
            "treatment": treatment,
            "pre_revenue_gbp_30d": pre_revenue,
            "revenue_gbp_30d": revenue,
            "paid_subscription_30d": paid,
        }
    )


def evaluate_pricing_experiment(frame: pd.DataFrame) -> tuple[pd.DataFrame, AssignmentIntegrity, PricingDecision]:
    integrity = assignment_integrity(frame)
    revenue = covariate_adjusted_effect(
        frame,
        outcome="revenue_gbp_30d",
        covariate="pre_revenue_gbp_30d",
    )
    paid = difference_in_proportions(frame, outcome="paid_subscription_30d")
    decision = pricing_decision(revenue, paid, integrity=integrity)
    estimates = pd.DataFrame(
        [
            {"metric": "revenue_gbp_30d", "analysis": "ancova_hc3", **asdict(revenue)},
            {"metric": "paid_subscription_30d", "analysis": "difference_in_proportions", **asdict(paid)},
        ]
    )
    return estimates, integrity, decision
