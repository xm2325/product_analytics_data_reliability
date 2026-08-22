import pandas as pd

from product_analytics.generator import generate_events
from product_analytics.quality import certify_events, certify_events_with_rejects, reconcile_revenue


def test_generator_is_deterministic():
    a = generate_events(days=10, seed=7)
    b = generate_events(days=10, seed=7)
    pd.testing.assert_frame_equal(a, b)


def test_certification_removes_controlled_faults():
    raw = generate_events(days=20, seed=11, inject_faults=True)
    silver, report = certify_events(raw)
    assert report.duplicate_event_rows > 0
    assert report.missing_identity_rows > 0
    assert report.rows_rejected == report.rows_raw - report.rows_certified
    assert len(silver) < len(raw)
    assert not silver["event_id"].duplicated().any()
    assert silver["user_id"].notna().all()


def test_rejected_rows_preserve_all_triggered_reasons():
    raw = pd.DataFrame(
        [
            {
                "event_id": "e1",
                "user_id": "u1",
                "product": "notes_app",
                "event_type": "first_open",
                "event_ts": "2026-01-01T00:00:00Z",
                "revenue_gbp": 0.0,
            },
            {
                "event_id": "e2",
                "user_id": None,
                "product": "unknown_product",
                "event_type": "mystery_event",
                "event_ts": "not-a-time",
                "revenue_gbp": -2.0,
            },
        ]
    )
    silver, report, rejected = certify_events_with_rejects(raw)
    assert len(silver) == 1
    assert report.rows_rejected == 1
    reasons = rejected.loc[0, "reject_reason"].split(";")
    assert set(reasons) == {
        "missing_identity",
        "invalid_timestamp",
        "invalid_revenue",
        "unknown_product",
        "unknown_event_type",
        "non_purchase_revenue",
    }


def test_reconciliation_detects_revenue_overstatement():
    raw = generate_events(days=30, seed=13, inject_faults=True)
    silver, _ = certify_events(raw)
    rec = reconcile_revenue(raw, silver)
    assert (rec["raw_revenue_gbp"] >= rec["certified_revenue_gbp"]).all()
    assert (rec["overstatement_gbp"] > 0).any()
