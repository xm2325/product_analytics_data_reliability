import math

import pandas as pd

import product_analytics.evidence_planning as evidence_planning
from product_analytics.evidence_planning import (
    certification_evidence_plan,
    cycle_stable_trials_for_exact_upper,
    required_trials_for_exact_upper,
    select_evidence_plan,
)
from product_analytics.uncertainty import exact_binomial_upper


def test_more_evidence_cannot_fix_planning_rate_at_or_above_budget():
    assert required_trials_for_exact_upper(0.005, 0.005, 0.001) is None
    assert required_trials_for_exact_upper(0.006, 0.005, 0.001) is None
    assert cycle_stable_trials_for_exact_upper(0.005, 0.005, 0.001) is None


def test_required_trials_produces_passing_conservative_count():
    rate = 0.003
    limit = 0.01
    alpha = 0.001
    n = required_trials_for_exact_upper(rate, limit, alpha)
    assert n is not None
    x = int(math.ceil(rate * n))
    assert exact_binomial_upper(x, n, alpha) <= limit


def test_cycle_stable_target_audits_full_next_count_jump_cycle():
    rate = 0.003
    limit = 0.01
    alpha = 0.001
    result = cycle_stable_trials_for_exact_upper(rate, limit, alpha)
    assert result is not None
    target, cycle = result
    assert cycle == math.ceil(1.0 / rate)
    for trials in range(target, target + cycle + 1):
        x = int(math.ceil(rate * trials))
        assert exact_binomial_upper(x, trials, alpha) <= limit


def test_cycle_stable_target_moves_past_local_sawtooth_failure(monkeypatch):
    # Simulate a first passing target at n=100 followed by a count-jump failure
    # at n=105. The stable planner must move beyond that local reversal rather
    # than report n=100 as if it were a monotone threshold.
    monkeypatch.setattr(
        evidence_planning,
        "required_trials_for_exact_upper",
        lambda planning_rate, limit, alpha, max_trials: 100,
    )
    monkeypatch.setattr(
        evidence_planning,
        "exact_binomial_upper",
        lambda successes, trials, alpha: 0.011 if trials == 105 else 0.009,
    )
    target, cycle = evidence_planning.cycle_stable_trials_for_exact_upper(
        0.2,
        0.01,
        0.001,
        max_trials=200,
    )
    assert cycle == 5
    assert target == 106


def _row(window, hours, late_rate, revision_rate, revenue, paid, events=100_000, cells=900, days=100):
    return {
        "window_index": window,
        "allowed_lateness_hours": float(hours),
        "late_event_fraction": float(late_rate),
        "revised_metric_cell_fraction": float(revision_rate),
        "max_abs_revenue_revision_gbp": float(revenue),
        "max_abs_paid_subscription_revision": float(paid),
        "finalizable_events": int(events),
        "finalized_metric_cells": int(cells),
        "finalized_calendar_dates": int(days),
    }


def test_evidence_plan_separates_sampling_gap_from_operational_breach():
    grid = pd.DataFrame(
        [
            _row(1, 24, 0.06, 0.02, 5, 1),
            _row(2, 24, 0.07, 0.02, 5, 1),
            _row(1, 48, 0.0048, 0.008, 12, 1),
            _row(2, 48, 0.0049, 0.009, 12, 1),
            _row(1, 72, 0.0048, 0.007, 12, 1),
            _row(2, 72, 0.0049, 0.008, 12, 1),
            _row(1, 96, 0.0040, 0.003, 0, 0),
            _row(2, 96, 0.0042, 0.004, 0, 0),
        ]
    )
    plan, contract = certification_evidence_plan(grid)
    rows = {float(row["allowed_lateness_hours"]): row for _, row in plan.iterrows()}

    assert bool(rows[24.0]["evidence_only_addressable"]) is False
    assert pd.isna(rows[24.0]["required_late_event_trials"])
    assert bool(rows[48.0]["evidence_only_addressable"]) is False
    assert bool(rows[72.0]["evidence_only_addressable"]) is False
    assert bool(rows[96.0]["evidence_only_addressable"]) is True
    assert rows[96.0]["required_late_event_trials"] > 0
    assert rows[96.0]["required_revised_metric_cells"] > 0
    assert rows[96.0]["late_event_audited_cycle_trials"] > 0
    assert rows[96.0]["revised_cell_audited_cycle_trials"] > 0
    assert contract["global_monotonic_threshold_claimed"] is False
    assert "cycle-stable target" in contract["evidence_target_semantics"]
    assert contract["budget_relaxed_for_planning"] is False
    assert contract["weighted_score_used"] is False


def test_evidence_plan_selector_chooses_shortest_sampling_only_candidate():
    plan = pd.DataFrame(
        [
            {
                "allowed_lateness_hours": 48.0,
                "evidence_only_addressable": False,
                "estimated_calendar_days_for_both_proportions": None,
                "planning_interpretation": "hard gate breach",
            },
            {
                "allowed_lateness_hours": 96.0,
                "evidence_only_addressable": True,
                "estimated_calendar_days_for_both_proportions": 400,
                "planning_interpretation": "evidence depth",
            },
        ]
    )
    decision = select_evidence_plan(plan)
    assert decision["status"] == "selected"
    assert decision["selected_lateness_hours"] == 96.0
    assert decision["estimated_calendar_days_for_both_proportions"] == 400
    assert decision["budget_relaxed_for_planning"] is False
