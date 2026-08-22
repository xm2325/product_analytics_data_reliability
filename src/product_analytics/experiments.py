from __future__ import annotations

from dataclasses import dataclass
from math import sqrt

import numpy as np
import pandas as pd
from scipy.stats import norm


@dataclass(frozen=True)
class EffectEstimate:
    effect: float
    se: float
    ci_low: float
    ci_high: float
    n_control: int
    n_treatment: int


def difference_in_means(frame: pd.DataFrame, outcome: str, treatment: str = "treatment") -> EffectEstimate:
    control = frame.loc[frame[treatment].eq(0), outcome].astype(float)
    treated = frame.loc[frame[treatment].eq(1), outcome].astype(float)
    if len(control) < 2 or len(treated) < 2:
        raise ValueError("Need at least two observations per arm")
    effect = float(treated.mean() - control.mean())
    se = sqrt(float(treated.var(ddof=1) / len(treated) + control.var(ddof=1) / len(control)))
    z = float(norm.ppf(0.975))
    return EffectEstimate(effect, se, effect - z * se, effect + z * se, len(control), len(treated))


def difference_in_proportions(frame: pd.DataFrame, outcome: str, treatment: str = "treatment") -> EffectEstimate:
    return difference_in_means(frame, outcome=outcome, treatment=treatment)


@dataclass(frozen=True)
class PricingDecision:
    action: str
    revenue_gate: bool
    paid_guardrail_gate: bool


def pricing_decision(
    revenue_effect: EffectEstimate,
    paid_effect: EffectEstimate,
    paid_harm_guardrail: float = -0.03,
) -> PricingDecision:
    """Require both positive commercial evidence and safety clearance.

    Revenue is not allowed to compensate mathematically for a paid-conversion
    harm state: the guardrail is non-compensatory.
    """
    revenue_gate = revenue_effect.ci_low > 0.0
    paid_gate = paid_effect.ci_low > paid_harm_guardrail
    action = "rollout" if revenue_gate and paid_gate else "hold"
    return PricingDecision(action, revenue_gate, paid_gate)
