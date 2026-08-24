from dataclasses import asdict

import pandas as pd
import pytest

from product_analytics.experiments import evaluate_pricing_experiment, generate_pricing_experiment
from product_analytics.impact_planning import (
    build_impact_plan,
    guardrail_evidence_plan,
    rollout_impact_scenario,
    summarise_impact_decision,
)


def _reference():
    users = generate_pricing_experiment(seed=2206, n_per_arm=4000)
    estimates, _, decision = evaluate_pricing_experiment(users)
    return users, estimates, decision


def test_reference_guardrail_evidence_target_matches_experiment_ci_definition():
    users, estimates, _ = _reference()
    paid = estimates.loc[estimates["metric"].eq("paid_subscription_30d")].iloc[0]
    plan = guardrail_evidence_plan(users)

    assert plan.current_ci_low == pytest.approx(float(paid["ci_low"]), abs=1e-12)
    assert plan.current_guardrail_passes is False
    assert plan.status == "additional_evidence_required"
    assert plan.equal_allocation_target_per_arm == 6393
    assert plan.additional_users_per_arm_from_current_minimum == 2393


def test_reference_hold_keeps_positive_impact_counterfactual_only():
    users, estimates, decision = _reference()
    scenario, evidence, summary, contract = build_impact_plan(users, estimates, asdict(decision))
    revenue = estimates.loc[estimates["metric"].eq("revenue_gbp_30d")].iloc[0]

    assert list(scenario["hypothetical_treated_users"]) == [25_000, 50_000, 75_000]
    assert int(scenario["hypothetical_treated_users"].sum()) == 150_000
    assert summary.counterfactual_incremental_revenue_gbp == pytest.approx(150_000 * float(revenue["effect"]))
    assert summary.counterfactual_incremental_revenue_ci_low_gbp == pytest.approx(150_000 * float(revenue["ci_low"]))
    assert summary.counterfactual_incremental_revenue_ci_high_gbp == pytest.approx(150_000 * float(revenue["ci_high"]))
    assert summary.planning_status == "counterfactual_only"
    assert summary.decision_authorised_rollout is False
    assert summary.authorised_treated_users == 0
    assert summary.authorised_incremental_revenue_gbp is None
    assert evidence.equal_allocation_target_per_arm == 6393
    assert contract["no_ltv_extrapolation"] is True


def test_rollout_action_authorises_same_fixed_volume_scenario():
    scenario = rollout_impact_scenario({"effect": 0.5, "ci_low": 0.2, "ci_high": 0.8})
    summary = summarise_impact_decision(scenario, {"action": "rollout"})

    assert summary.planning_status == "decision_authorised"
    assert summary.decision_authorised_rollout is True
    assert summary.authorised_treated_users == 150_000
    assert summary.authorised_incremental_revenue_gbp == pytest.approx(75_000.0)


def test_guardrail_point_estimate_at_or_below_margin_is_not_fixed_by_sample_size():
    frame = pd.DataFrame(
        {
            "treatment": [0] * 100 + [1] * 100,
            "paid_subscription_30d": [1] * 20 + [0] * 80 + [1] * 15 + [0] * 85,
        }
    )
    plan = guardrail_evidence_plan(frame, harm_margin=-0.03)

    assert plan.observed_difference == pytest.approx(-0.05)
    assert plan.status == "structural_point_estimate_failure"
    assert plan.equal_allocation_target_per_arm is None
    assert plan.additional_users_per_arm_from_current_minimum is None


def test_rollout_scenario_rejects_incoherent_effect_interval():
    with pytest.raises(ValueError, match="inside its confidence interval"):
        rollout_impact_scenario({"effect": 0.5, "ci_low": 0.6, "ci_high": 0.8})
