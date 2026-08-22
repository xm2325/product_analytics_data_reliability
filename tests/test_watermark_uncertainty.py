import math

import pandas as pd

from product_analytics.uncertainty import (
    exact_binomial_upper,
    select_certified_watermark_policy,
    watermark_uncertainty_grid,
    watermark_uncertainty_summary,
)


def _row(window, hours, late, finalizable, revised, cells, revenue=0.0, paid=0.0, feasible=True):
    return {
        "window_index": window,
        "allowed_lateness_hours": float(hours),
        "finalizable_events": int(finalizable),
        "late_beyond_watermark_events": int(late),
        "late_event_fraction": late / finalizable,
        "finalized_metric_cells": int(cells),
        "revised_metric_cells": int(revised),
        "revised_metric_cell_fraction": revised / cells,
        "max_abs_revenue_revision_gbp": float(revenue),
        "max_abs_paid_subscription_revision": float(paid),
        "feasible": bool(feasible),
    }


def test_exact_binomial_upper_handles_zero_and_all_successes():
    upper_zero = exact_binomial_upper(0, 100, 0.05)
    assert 0.0 < upper_zero < 0.1
    assert math.isclose(exact_binomial_upper(100, 100, 0.05), 1.0)


def test_uncertainty_grid_uses_full_selection_family_for_bonferroni():
    grid = pd.DataFrame(
        [
            _row(1, 48, 1, 1000, 0, 300),
            _row(1, 96, 0, 1000, 0, 300),
            _row(2, 48, 1, 1000, 0, 300),
            _row(2, 96, 0, 1000, 0, 300),
        ]
    )
    certified, contract = watermark_uncertainty_grid(grid, family_alpha=0.05)
    assert contract["simultaneous_one_sided_bounds"] == 8
    assert math.isclose(contract["per_bound_alpha"], 0.05 / 8)
    assert (certified["late_event_fraction_upper"] >= certified["late_event_fraction"]).all()
    assert (
        certified["revised_metric_cell_fraction_upper"]
        >= certified["revised_metric_cell_fraction"]
    ).all()
    assert contract["weighted_score_used"] is False


def test_uncertainty_can_withhold_certification_when_point_estimate_passes():
    # Zero revisions out of only 100 cells has a non-trivial exact upper bound.
    grid = pd.DataFrame([_row(1, 96, 0, 1000, 0, 100, feasible=True)])
    certified, _ = watermark_uncertainty_grid(grid, family_alpha=0.05)
    row = certified.iloc[0]
    assert row["revised_metric_cell_fraction"] == 0.0
    assert row["revised_metric_cell_fraction_upper"] > 0.01
    assert bool(row["certified_under_binomial_model"]) is False


def test_summary_distinguishes_observed_feasibility_from_certification():
    grid = pd.DataFrame(
        [
            _row(1, 96, 0, 100000, 0, 1000, feasible=True),
            _row(2, 96, 0, 100000, 0, 1000, feasible=True),
        ]
    )
    certified, _ = watermark_uncertainty_grid(grid, family_alpha=0.05)
    summary = watermark_uncertainty_summary(certified)
    row = summary.iloc[0]
    assert row["observed_feasible_windows"] == 2
    assert row["certified_windows"] <= row["observed_feasible_windows"]
    assert 0.0 <= row["certification_rate"] <= 1.0


def test_selector_returns_none_instead_of_relaxing_uncertainty_gate():
    summary = pd.DataFrame(
        [
            {
                "allowed_lateness_hours": 48.0,
                "windows": 9,
                "certified_windows": 0,
                "certification_rate": 0.0,
                "certified_all_windows": False,
            },
            {
                "allowed_lateness_hours": 96.0,
                "windows": 9,
                "certified_windows": 8,
                "certification_rate": 8 / 9,
                "certified_all_windows": False,
            },
        ]
    )
    decision = select_certified_watermark_policy(
        summary,
        {
            "family_confidence_level": 0.95,
            "correction": "bonferroni",
            "per_bound_alpha": 0.001,
        },
    )
    assert decision["status"] == "no_candidate_certified_familywise_95"
    assert decision["selected_lateness_hours"] is None
    assert decision["budget_relaxed_after_uncertainty"] is False


def test_selector_chooses_shortest_all_window_certified_candidate():
    summary = pd.DataFrame(
        [
            {
                "allowed_lateness_hours": 48.0,
                "windows": 9,
                "certified_windows": 8,
                "certification_rate": 8 / 9,
                "certified_all_windows": False,
            },
            {
                "allowed_lateness_hours": 72.0,
                "windows": 9,
                "certified_windows": 9,
                "certification_rate": 1.0,
                "certified_all_windows": True,
            },
            {
                "allowed_lateness_hours": 96.0,
                "windows": 9,
                "certified_windows": 9,
                "certification_rate": 1.0,
                "certified_all_windows": True,
            },
        ]
    )
    decision = select_certified_watermark_policy(
        summary,
        {
            "family_confidence_level": 0.95,
            "correction": "bonferroni",
            "per_bound_alpha": 0.001,
        },
    )
    assert decision["status"] == "selected"
    assert decision["selected_lateness_hours"] == 72.0
