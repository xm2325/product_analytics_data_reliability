import numpy as np
import pandas as pd
import pytest

from product_analytics.experiments import (
    AssignmentIntegrity,
    EffectEstimate,
    assignment_integrity,
    covariate_adjusted_effect,
    evaluate_pricing_experiment,
    generate_pricing_experiment,
    pricing_decision,
)


def test_revenue_cannot_compensate_for_guardrail_failure():
    revenue = EffectEstimate(2.0, 0.2, 1.6, 2.4, 500, 500)
    harmful_paid = EffectEstimate(-0.02, 0.01, -0.04, 0.0, 500, 500)
    decision = pricing_decision(revenue, harmful_paid, paid_harm_guardrail=-0.03)
    assert decision.revenue_gate
    assert not decision.paid_guardrail_gate
    assert decision.action == "hold"


def test_assignment_integrity_accepts_exact_balance():
    frame = pd.DataFrame({"treatment": [0] * 100 + [1] * 100})
    integrity = assignment_integrity(frame)
    assert integrity.n_control == 100
    assert integrity.n_treatment == 100
    assert integrity.p_value == 1.0
    assert integrity.passes


def test_assignment_integrity_rejects_fractional_assignment():
    frame = pd.DataFrame({"treatment": [0.0, 0.5, 1.0, 1.0]})
    with pytest.raises(ValueError, match="binary 0/1"):
        assignment_integrity(frame)


def test_sample_ratio_mismatch_invalidates_decision():
    integrity = AssignmentIntegrity(1000, 900, 100, 0.5, 0.1, 0.0, 0.001, False)
    revenue = EffectEstimate(1.0, 0.1, 0.8, 1.2, 900, 100)
    paid = EffectEstimate(0.0, 0.005, -0.01, 0.01, 900, 100)
    decision = pricing_decision(revenue, paid, integrity=integrity)
    assert decision.action == "invalid"
    assert not decision.assignment_integrity_gate


def test_covariate_adjustment_recovers_positive_treatment_effect():
    rng = np.random.default_rng(7)
    n = 2000
    treatment = np.repeat([0, 1], n // 2)
    pre = rng.normal(size=n)
    outcome = 3.0 * pre + 0.8 * treatment + rng.normal(scale=1.0, size=n)
    frame = pd.DataFrame({"treatment": treatment, "pre": pre, "outcome": outcome})
    estimate = covariate_adjusted_effect(frame, outcome="outcome", covariate="pre")
    assert 0.65 < estimate.effect < 0.95
    assert estimate.ci_low > 0.0


def test_reference_experiment_holds_on_uncertain_paid_guardrail():
    frame = generate_pricing_experiment(seed=2206, n_per_arm=4000)
    estimates, integrity, decision = evaluate_pricing_experiment(frame)
    revenue = estimates.loc[estimates["metric"].eq("revenue_gbp_30d")].iloc[0]
    paid = estimates.loc[estimates["metric"].eq("paid_subscription_30d")].iloc[0]

    assert integrity.passes
    assert revenue["ci_low"] > 0.0
    assert paid["effect"] > -0.03
    assert paid["ci_low"] < -0.03
    assert decision.revenue_gate
    assert not decision.paid_guardrail_gate
    assert decision.action == "hold"


def test_reference_experiment_is_reproducible_and_balanced():
    left = generate_pricing_experiment(seed=2206, n_per_arm=50)
    right = generate_pricing_experiment(seed=2206, n_per_arm=50)
    pd.testing.assert_frame_equal(left, right)
    assert int(left["treatment"].sum()) == 50
