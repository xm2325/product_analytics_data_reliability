from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class ForecastGate:
    max_mape: float = 0.20
    min_holdout_points: int = 14


@dataclass(frozen=True)
class ForecastEvaluation:
    metric: str
    holdout_points: int
    mape: float
    approved: bool
    reason: str


def seasonal_naive(series: pd.Series, season: int = 7, holdout: int = 28) -> pd.DataFrame:
    y = pd.Series(series, dtype=float).reset_index(drop=True)
    if len(y) <= season + holdout:
        raise ValueError("Series is too short for requested season/holdout")
    start = len(y) - holdout
    pred = []
    for i in range(start, len(y)):
        pred.append(y.iloc[i - season])
    return pd.DataFrame({"actual": y.iloc[start:].to_numpy(), "forecast": np.asarray(pred, dtype=float)})


def evaluate_forecast(metric: str, backtest: pd.DataFrame, gate: ForecastGate = ForecastGate()) -> ForecastEvaluation:
    actual = backtest["actual"].astype(float)
    forecast = backtest["forecast"].astype(float)
    denom = actual.abs().replace(0, np.nan)
    mape = float(((actual - forecast).abs() / denom).dropna().mean())
    enough = len(backtest) >= gate.min_holdout_points
    approved = bool(enough and np.isfinite(mape) and mape <= gate.max_mape)
    if not enough:
        reason = "insufficient holdout"
    elif not np.isfinite(mape):
        reason = "MAPE not estimable"
    elif mape > gate.max_mape:
        reason = f"MAPE {mape:.3f} exceeds {gate.max_mape:.3f}"
    else:
        reason = "planning gate passed"
    return ForecastEvaluation(metric, len(backtest), mape, approved, reason)
