import pandas as pd

from product_analytics.forecasting import ForecastGate, evaluate_forecast, seasonal_naive


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
