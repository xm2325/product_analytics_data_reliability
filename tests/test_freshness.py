import pandas as pd

from product_analytics.freshness import (
    LateArrivalPolicy,
    WatermarkRiskBudget,
    available_as_of,
    late_after_watermark_snapshot,
    late_arrival_summary,
    metric_revision_report,
    rolling_watermark_backtest,
    select_stable_watermark_policy,
    select_watermark_policy,
    watermark_event_date,
    watermark_policy_grid,
    watermark_stability_summary,
)
from product_analytics.generator import generate_events
from product_analytics.quality import certify_events, certify_events_with_rejects, idempotent_backfill


def _event(event_id, event_type, event_ts, ingested_at, user_id="u1", revenue=0.0):
    return {
        "event_id": event_id,
        "user_id": user_id,
        "product": "notes_app",
        "event_type": event_type,
        "event_ts": pd.Timestamp(event_ts),
        "ingested_at": pd.Timestamp(ingested_at),
        "platform": "ios",
        "source": "organic",
        "revenue_gbp": revenue,
    }


def test_generated_processing_time_is_deterministic_and_never_precedes_event_time():
    a = generate_events(days=20, seed=41, inject_faults=False)
    b = generate_events(days=20, seed=41, inject_faults=False)
    pd.testing.assert_series_equal(a["ingested_at"], b["ingested_at"])
    assert a["ingested_at"].ge(a["event_ts"]).all()
    summary = late_arrival_summary(a, LateArrivalPolicy(allowed_lateness_hours=48.0))
    assert summary["late_beyond_watermark"].sum() > 0


def test_legacy_input_without_ingested_at_is_treated_as_immediate_arrival():
    raw = pd.DataFrame(
        [
            {
                "event_id": "e1",
                "user_id": "u1",
                "product": "notes_app",
                "event_type": "first_open",
                "event_ts": "2026-01-01T08:00:00Z",
                "revenue_gbp": 0.0,
            }
        ]
    )
    silver, report = certify_events(raw)
    assert report.rows_rejected == 0
    assert report.invalid_ingestion_timestamp_rows == 0
    assert report.ingestion_before_event_rows == 0
    assert silver.loc[0, "ingested_at"] == silver.loc[0, "event_ts"]


def test_explicit_processing_time_before_event_is_rejected():
    raw = pd.DataFrame(
        [
            _event(
                "e1",
                "first_open",
                "2026-01-02T08:00:00Z",
                "2026-01-01T08:00:00Z",
            )
        ]
    )
    silver, report, rejected = certify_events_with_rejects(raw)
    assert silver.empty
    assert report.ingestion_before_event_rows == 1
    assert rejected.loc[0, "reject_reason"] == "ingestion_before_event"


def test_processing_snapshot_excludes_not_yet_arrived_rows():
    events = pd.DataFrame(
        [
            _event("e1", "first_open", "2026-01-01T08:00:00Z", "2026-01-01T09:00:00Z"),
            _event("e2", "app_open", "2026-01-01T08:01:00Z", "2026-01-05T09:00:00Z"),
        ]
    )
    snapshot = available_as_of(events, "2026-01-03T23:59:59Z")
    assert set(snapshot["event_id"]) == {"e1"}


def test_watermark_flags_future_arrival_on_nominally_final_event_date():
    policy = LateArrivalPolicy(allowed_lateness_hours=48.0)
    events = pd.DataFrame(
        [
            _event("e1", "first_open", "2026-01-01T08:00:00Z", "2026-01-01T09:00:00Z"),
            _event("e2", "app_open", "2026-01-02T08:00:00Z", "2026-01-06T08:00:00Z"),
        ]
    )
    as_of = "2026-01-05T23:59:59Z"
    assert str(watermark_event_date(as_of, policy)) == "2026-01-03"
    late = late_after_watermark_snapshot(events, as_of, policy)
    assert list(late["event_id"]) == ["e2"]

    revisions = metric_revision_report(events, as_of, policy)
    changed = revisions.loc[revisions["changed_after_watermark"]]
    assert not changed.empty
    assert "dau" in set(changed["metric"])


def test_late_arrival_backfill_is_idempotent():
    full = pd.DataFrame(
        [
            _event("e1", "first_open", "2026-01-01T08:00:00Z", "2026-01-01T09:00:00Z"),
            _event("e2", "app_open", "2026-01-02T08:00:00Z", "2026-01-06T08:00:00Z"),
        ]
    )
    snapshot = available_as_of(full, "2026-01-05T23:59:59Z")
    correction = full.loc[full["event_id"].eq("e2")].copy()
    once = idempotent_backfill(snapshot, correction)
    twice = idempotent_backfill(once, correction)
    pd.testing.assert_frame_equal(once, twice)
    assert set(once["event_id"]) == {"e1", "e2"}


def test_policy_grid_uses_only_finalizable_event_dates_for_decision_fraction():
    historical = [
        _event("e1", "first_open", "2026-01-01T08:00:00Z", "2026-01-01T09:00:00Z", "u1"),
        _event("e2", "app_open", "2026-01-02T08:00:00Z", "2026-01-06T08:00:00Z", "u2"),
    ]
    future = [
        _event("e3", "app_open", "2026-02-01T08:00:00Z", "2026-02-10T08:00:00Z", "u3"),
        _event("e4", "app_open", "2026-02-02T08:00:00Z", "2026-02-12T08:00:00Z", "u4"),
    ]
    budget = WatermarkRiskBudget(
        max_late_event_fraction=1.0,
        max_revised_metric_cell_fraction=1.0,
        max_abs_revenue_revision_gbp=999.0,
        max_abs_paid_subscription_revision=999.0,
    )
    as_of = "2026-01-10T23:59:59Z"
    base = watermark_policy_grid(pd.DataFrame(historical), as_of, candidate_hours=(48,), budget=budget)
    with_future = watermark_policy_grid(
        pd.DataFrame(historical + future), as_of, candidate_hours=(48,), budget=budget
    )

    assert base.loc[0, "finalizable_events"] == with_future.loc[0, "finalizable_events"]
    assert base.loc[0, "late_event_fraction"] == with_future.loc[0, "late_event_fraction"]
    assert with_future.loc[0, "settled_stream_events"] > base.loc[0, "settled_stream_events"]
    assert with_future.loc[0, "whole_stream_late_event_fraction"] != base.loc[0, "whole_stream_late_event_fraction"]


def test_watermark_policy_grid_exposes_latency_risk_tradeoff():
    events = pd.DataFrame(
        [
            _event("e1", "first_open", "2026-01-01T08:00:00Z", "2026-01-01T09:00:00Z", "u1"),
            _event("e2", "app_open", "2026-01-01T09:00:00Z", "2026-01-02T15:00:00Z", "u2"),
            _event("e3", "app_open", "2026-01-02T08:00:00Z", "2026-01-04T20:00:00Z", "u3"),
            _event("e4", "app_open", "2026-01-02T09:00:00Z", "2026-01-06T13:00:00Z", "u4"),
        ]
    )
    grid = watermark_policy_grid(
        events,
        "2026-01-05T23:59:59Z",
        candidate_hours=(24, 48, 72, 96),
        budget=WatermarkRiskBudget(
            max_late_event_fraction=1.0,
            max_revised_metric_cell_fraction=1.0,
            max_abs_revenue_revision_gbp=999.0,
            max_abs_paid_subscription_revision=999.0,
        ),
    )
    assert list(grid["allowed_lateness_hours"]) == [24.0, 48.0, 72.0, 96.0]
    assert grid["whole_stream_late_event_fraction"].is_monotonic_decreasing
    assert grid["finalizable_events"].is_monotonic_decreasing
    assert grid["finalized_calendar_dates"].is_monotonic_decreasing
    assert (grid["finalization_lag_days"] == grid["allowed_lateness_hours"] / 24.0).all()


def test_policy_selection_uses_shortest_feasible_candidate_without_weighted_score():
    grid = pd.DataFrame(
        [
            {
                "allowed_lateness_hours": 24.0,
                "feasible": False,
                "late_event_fraction": 0.02,
                "revised_metric_cell_fraction": 0.02,
                "max_abs_revenue_revision_gbp": 5.0,
                "max_abs_paid_subscription_revision": 1.0,
            },
            {
                "allowed_lateness_hours": 48.0,
                "feasible": True,
                "late_event_fraction": 0.004,
                "revised_metric_cell_fraction": 0.008,
                "max_abs_revenue_revision_gbp": 8.0,
                "max_abs_paid_subscription_revision": 1.0,
                "finalizable_events": 100,
            },
            {
                "allowed_lateness_hours": 72.0,
                "feasible": True,
                "late_event_fraction": 0.003,
                "revised_metric_cell_fraction": 0.004,
                "max_abs_revenue_revision_gbp": 0.0,
                "max_abs_paid_subscription_revision": 0.0,
                "finalizable_events": 90,
            },
        ]
    )
    decision = select_watermark_policy(grid)
    assert decision["status"] == "selected"
    assert decision["selected_lateness_hours"] == 48.0
    assert decision["weighted_score_used"] is False
    assert decision["late_event_fraction_scope"] == "event_date_on_or_before_candidate_watermark"
    assert "shortest candidate" in decision["selection_rule"]


def test_rolling_backtest_preserves_windows_and_stability_contract():
    events = pd.DataFrame(
        [
            _event("e1", "first_open", "2026-01-01T08:00:00Z", "2026-01-01T09:00:00Z", "u1"),
            _event("e2", "app_open", "2026-01-02T08:00:00Z", "2026-01-02T10:00:00Z", "u2"),
            _event("e3", "app_open", "2026-01-03T08:00:00Z", "2026-01-03T10:00:00Z", "u3"),
        ]
    )
    budget = WatermarkRiskBudget(
        max_late_event_fraction=1.0,
        max_revised_metric_cell_fraction=1.0,
        max_abs_revenue_revision_gbp=999.0,
        max_abs_paid_subscription_revision=999.0,
    )
    grid, windows = rolling_watermark_backtest(
        events,
        processing_snapshots=("2026-01-06T23:59:59Z", "2026-01-07T23:59:59Z"),
        candidate_hours=(24, 48),
        budget=budget,
    )
    assert grid["window_index"].nunique() == 2
    assert len(grid) == 4
    assert len(windows) == 2
    assert windows["selected_lateness_hours"].eq(24.0).all()

    stability = watermark_stability_summary(grid)
    assert stability["windows"].eq(2).all()
    assert stability["stable_all_windows"].all()
    decision = select_stable_watermark_policy(stability, budget)
    assert decision["selected_lateness_hours"] == 24.0
    assert decision["weighted_score_used"] is False
    assert decision["budget_relaxed_after_backtest"] is False


def test_stable_selector_reports_no_policy_instead_of_relaxing_budget():
    stability = pd.DataFrame(
        [
            {"allowed_lateness_hours": 24.0, "windows": 10, "feasible_windows": 2, "stable_all_windows": False},
            {"allowed_lateness_hours": 48.0, "windows": 10, "feasible_windows": 9, "stable_all_windows": False},
            {"allowed_lateness_hours": 72.0, "windows": 10, "feasible_windows": 9, "stable_all_windows": False},
        ]
    )
    decision = select_stable_watermark_policy(stability)
    assert decision["status"] == "no_candidate_stable_in_all_windows"
    assert decision["selected_lateness_hours"] is None
    assert decision["budget_relaxed_after_backtest"] is False
