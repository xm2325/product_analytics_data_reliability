import pandas as pd

from product_analytics.generator import generate_events
from product_analytics.quality import certify_events, reconcile_revenue


def test_generator_is_deterministic():
    a = generate_events(days=10, seed=7)
    b = generate_events(days=10, seed=7)
    pd.testing.assert_frame_equal(a, b)


def test_certification_removes_controlled_faults():
    raw = generate_events(days=20, seed=11, inject_faults=True)
    silver, report = certify_events(raw)
    assert report.duplicate_event_rows > 0
    assert report.missing_identity_rows > 0
    assert len(silver) < len(raw)
    assert not silver["event_id"].duplicated().any()
    assert silver["user_id"].notna().all()


def test_reconciliation_detects_revenue_overstatement():
    raw = generate_events(days=30, seed=13, inject_faults=True)
    silver, _ = certify_events(raw)
    rec = reconcile_revenue(raw, silver)
    assert (rec["raw_revenue_gbp"] >= rec["certified_revenue_gbp"]).all()
    assert (rec["overstatement_gbp"] > 0).any()
