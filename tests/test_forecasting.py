import pandas as pd

from product_analytics.forecasting import ForecastGate, evaluate_forecast, mature_metric_history, seasonal_naive


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
