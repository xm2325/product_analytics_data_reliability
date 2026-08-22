from product_analytics.experiments import EffectEstimate, pricing_decision


def test_revenue_cannot_compensate_for_guardrail_failure():
    revenue = EffectEstimate(2.0, 0.2, 1.6, 2.4, 500, 500)
    harmful_paid = EffectEstimate(-0.02, 0.01, -0.04, 0.0, 500, 500)
    decision = pricing_decision(revenue, harmful_paid, paid_harm_guardrail=-0.03)
    assert decision.revenue_gate
    assert not decision.paid_guardrail_gate
    assert decision.action == "hold"
