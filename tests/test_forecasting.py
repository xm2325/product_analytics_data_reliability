import math

import pandas as pd
import pytest

from product_analytics.forecasting import (
    ForecastGate,
    ForecastPlanningGate,
    _finite_sample_absolute_residual_radius,
    evaluate_forecast,
    evaluate_forecast_plan,
    forecast_decision_contract,
    forecast_reconciliation,
    mature_metric_history,
    rolling_origin_seasonal_naive,
    seasonal_naive,
)


def test_forecast_gate_approves_stable_series():
    series = pd.Series([100 + (i % 7) for i in range(80)], dtype=float)
    bt = seasonal_naive(series, season=7, holdout=28)
    result = evaluate_forecast("dau", bt, ForecastGate(max_mape=0.05))
    assert result.approved
    assert result.mape == 0.0


def test_forecast_gate_withholds_bad_predictions():
    bt = pd.DataFrame({"actual": [100.0] * 20, "forecast": [50.0] * 20})
    result = evaluate_forecast("revenue", bt, ForecastGate(max_mape=0.20, min_holdout_points=14))
    assert not result.approved


def test_mature_history_excludes_post_acquisition_tail():
    gold = pd.DataFrame(
        {
            "product": ["notes_app"] * 5,
            "date": pd.date_range("2026-01-01", periods=5).date,
            "dau": [100, 101, 99, 8, 3],
        }
    )
    certified = pd.DataFrame(
        {
            "product": ["notes_app"] * 3 + ["notes_app"],
            "event_type": ["first_open", "first_open", "first_open", "purchase"],
            "event_ts": pd.to_datetime(
                ["2026-01-01", "2026-01-02", "2026-01-03", "2026-01-05"], utc=True
            ),
        }
    )
    history, cutoff = mature_metric_history(gold, certified, "notes_app")
    assert str(cutoff) == "2026-01-03"
    assert history["date"].max().isoformat() == "2026-01-03"
    assert len(history) == 3


def _weekly_frame(periods: int = 70) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": pd.date_range("2026-01-01", periods=periods),
            "dau": [100.0 + (index % 7) for index in range(periods)],
        }
    )


def test_rolling_origin_uses_only_data_available_at_each_origin():
    backtest = rolling_origin_seasonal_naive(_weekly_frame(), "dau", origins=4, horizon_days=7)
    assert len(backtest) == 28
    assert backtest["origin_index"].nunique() == 4
    assert (pd.to_datetime(backtest["seasonal_source_date"]) <= pd.to_datetime(backtest["origin_date"])).all()
    assert (pd.to_datetime(backtest["target_date"]) > pd.to_datetime(backtest["origin_date"])).all()
    assert (backtest["forecast"] == backtest["actual"]).all()


def test_rolling_origin_rejects_recursive_horizon_that_would_leak_holdout_values():
    with pytest.raises(ValueError, match="cannot exceed season"):
        rolling_origin_seasonal_naive(_weekly_frame(), "dau", season=7, horizon_days=8, origins=2)


def test_conformal_radius_uses_declared_finite_sample_order_statistic():
    residuals = pd.Series(range(1, 11), dtype=float).to_numpy()
    # n=10, alpha=.2 => ceil(11*.8)=9, so the ninth absolute residual is 9.
    assert _finite_sample_absolute_residual_radius(residuals, 0.20) == 9.0


def test_planning_gate_approves_accurate_seasonal_signal():
    backtest = rolling_origin_seasonal_naive(_weekly_frame(), "dau", origins=4, horizon_days=7)
    result = evaluate_forecast_plan(
        "notes_app:dau",
        backtest,
        ForecastPlanningGate(max_mape=0.05, max_wape=0.05, min_interval_coverage=0.90),
    )
    assert result.approved
    assert result.wape == 0.0
    assert result.benchmark_wape > result.wape
    assert result.interval_coverage == 1.0


def test_planning_gate_withholds_candidate_that_loses_to_simpler_benchmark():
    backtest = pd.DataFrame(
        {
            "origin_index": [1, 1, 2, 2],
            "horizon_day": [1, 2, 1, 2],
            "actual": [100.0, 100.0, 100.0, 100.0],
            "forecast": [90.0, 90.0, 90.0, 90.0],
            "benchmark_forecast": [100.0, 100.0, 100.0, 100.0],
            "interval_low": [80.0] * 4,
            "interval_high": [110.0] * 4,
        }
    )
    result = evaluate_forecast_plan(
        "photo_editor:dau",
        backtest,
        ForecastPlanningGate(
            max_mape=0.20,
            max_wape=0.20,
            min_backtest_points=4,
            min_interval_coverage=0.80,
        ),
    )
    assert not result.approved
    assert result.absolute_accuracy_gate
    assert not result.benchmark_gate
    assert "benchmark" in result.reason


def test_reconciliation_preserves_plan_vs_actual_totals_per_origin():
    backtest = rolling_origin_seasonal_naive(_weekly_frame(), "dau", origins=2, horizon_days=7)
    reconciliation = forecast_reconciliation("notes_app:dau", backtest)
    assert len(reconciliation) == 2
    assert (reconciliation["planned_total"] == reconciliation["actual_total"]).all()
    assert (reconciliation["signed_error"] == 0.0).all()
    assert (reconciliation["absolute_pct_error"] == 0.0).all()


def test_forecast_contract_makes_non_compensatory_rules_explicit():
    contract = forecast_decision_contract()
    assert contract["weighted_score_used"] is False
    assert contract["future_data_leakage_allowed"] is False
    assert contract["backtest_points_per_metric"] == 28
    assert math.isclose(contract["interval_nominal_coverage"], 0.90)
    assert contract["planning_gate"]["require_noninferior_wape_to_benchmark"] is True
