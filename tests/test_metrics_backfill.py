import pandas as pd

from product_analytics.generator import generate_events
from product_analytics.metrics import METRIC_CONTRACTS, portfolio_conversion
from product_analytics.quality import certify_events, idempotent_backfill


def test_metric_contracts_keep_denominators_explicit():
    first = METRIC_CONTRACTS["paid_conversion_from_first_open"]
    trial = METRIC_CONTRACTS["paid_conversion_from_trial_start"]
    assert first.denominator != trial.denominator


def test_conditional_conversion_exceeds_broad_funnel_conversion_in_reference_generator():
    raw = generate_events(days=30, seed=17, inject_faults=False)
    silver, _ = certify_events(raw)
    rates = portfolio_conversion(silver)
    assert rates["paid_conversion_from_trial_start"] > rates["paid_conversion_from_first_open"]


def test_backfill_is_idempotent():
    current = pd.DataFrame({"event_id": ["a", "b"], "revenue_gbp": [10.0, 20.0]})
    correction = pd.DataFrame({"event_id": ["b"], "revenue_gbp": [15.0]})
    once = idempotent_backfill(current, correction)
    twice = idempotent_backfill(once, correction)
    pd.testing.assert_frame_equal(once, twice)
