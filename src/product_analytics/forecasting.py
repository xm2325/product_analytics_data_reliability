from __future__ import annotations

from dataclasses import asdict, dataclass
from math import ceil

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class ForecastGate:
    """Legacy single-holdout gate retained for backwards-compatible examples."""

    max_mape: float = 0.20
    min_holdout_points: int = 14


@dataclass(frozen=True)
class ForecastEvaluation:
    metric: str
    holdout_points: int
    mape: float
    approved: bool
    reason: str


@dataclass(frozen=True)
class ForecastPlanningGate:
    """Non-compensatory planning gate for rolling-origin forecast evidence."""

    max_mape: float = 0.20
    max_wape: float = 0.20
    min_backtest_points: int = 28
    min_interval_coverage: float = 0.85
    require_noninferior_wape_to_benchmark: bool = True


@dataclass(frozen=True)
class ForecastPlanningEvaluation:
    metric: str
    model: str
    benchmark: str
    origins: int
    horizon_days: int
    backtest_points: int
    mape: float
    wape: float
    benchmark_mape: float
    benchmark_wape: float
    relative_wape_improvement: float
    interval_nominal_coverage: float
    interval_coverage: float
    enough_backtest_gate: bool
    absolute_accuracy_gate: bool
    benchmark_gate: bool
    interval_coverage_gate: bool
    approved: bool
    reason: str


DEFAULT_FORECAST_SEASON = 7
DEFAULT_FORECAST_HORIZON = 7
DEFAULT_FORECAST_ORIGINS = 4
DEFAULT_INTERVAL_ALPHA = 0.10
DEFAULT_FORECAST_PLANNING_GATE = ForecastPlanningGate()


def mature_metric_history(
    gold_metrics: pd.DataFrame,
    certified_events: pd.DataFrame,
    product: str,
    boundary_event: str = "first_open",
) -> tuple[pd.DataFrame, object]:
    """Trim generator-edge outcome tails before forecast validation.

    The synthetic acquisition process stops at a fixed horizon, while trials,
    subscriptions and purchases can arrive later. Those later outcomes belong
    in historical metrics, but the artificial post-acquisition tail should not
    be treated as a normal forecasting holdout. The last boundary-event date
    is therefore the observation cutoff for forecast evaluation.
    """
    boundary = certified_events.loc[
        certified_events["product"].eq(product) & certified_events["event_type"].eq(boundary_event),
        "event_ts",
    ]
    if boundary.empty:
        raise ValueError(f"No {boundary_event!r} events for product {product!r}")
    cutoff = pd.to_datetime(boundary, utc=True).dt.date.max()
    history = gold_metrics.loc[
        gold_metrics["product"].eq(product) & gold_metrics["date"].le(cutoff)
    ].copy()
    return history.sort_values("date").reset_index(drop=True), cutoff


def seasonal_naive(series: pd.Series, season: int = 7, holdout: int = 28) -> pd.DataFrame:
    """Legacy single terminal holdout used by earlier project versions."""
    y = pd.Series(series, dtype=float).reset_index(drop=True)
    if len(y) <= season + holdout:
        raise ValueError("Series is too short for requested season/holdout")
    start = len(y) - holdout
    pred = []
    for i in range(start, len(y)):
        pred.append(y.iloc[i - season])
    return pd.DataFrame({"actual": y.iloc[start:].to_numpy(), "forecast": np.asarray(pred, dtype=float)})


def evaluate_forecast(metric: str, backtest: pd.DataFrame, gate: ForecastGate = ForecastGate()) -> ForecastEvaluation:
    """Legacy MAPE-only gate retained so historical examples remain executable."""
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


def _finite_sample_absolute_residual_radius(residuals: np.ndarray, alpha: float) -> float:
    """Conservative split-conformal absolute-residual quantile.

    Rank is ceil((n + 1) * (1 - alpha)), capped at n. Using an explicit order
    statistic keeps generator and validator semantics stable across NumPy
    quantile interpolation defaults.
    """
    values = np.asarray(residuals, dtype=float)
    if values.ndim != 1 or len(values) == 0 or not np.isfinite(values).all():
        raise ValueError("Calibration residuals must be a finite non-empty vector")
    if not 0.0 < alpha < 1.0:
        raise ValueError("alpha must be between 0 and 1")
    ordered = np.sort(np.abs(values))
    rank = min(len(ordered), ceil((len(ordered) + 1) * (1.0 - alpha)))
    return float(ordered[rank - 1])


def rolling_origin_seasonal_naive(
    frame: pd.DataFrame,
    metric: str,
    *,
    date_column: str = "date",
    season: int = DEFAULT_FORECAST_SEASON,
    horizon_days: int = DEFAULT_FORECAST_HORIZON,
    origins: int = DEFAULT_FORECAST_ORIGINS,
    interval_alpha: float = DEFAULT_INTERVAL_ALPHA,
) -> pd.DataFrame:
    """Leakage-safe rolling-origin weekly seasonal-naive backtest.

    Each origin forecasts the next ``horizon_days`` using only lag-season
    observations available at the origin. The benchmark carries the final
    observed value at that origin across the whole horizon. Prediction-interval
    radii are calibrated only from seasonal residuals available before each
    origin.
    """
    if metric not in frame.columns or date_column not in frame.columns:
        raise ValueError(f"Missing {metric!r} or {date_column!r}")
    if season < 1 or horizon_days < 1 or origins < 1:
        raise ValueError("season, horizon_days and origins must be positive")
    if horizon_days > season:
        raise ValueError("horizon_days cannot exceed season without recursive forecasts")

    ordered = frame[[date_column, metric]].copy()
    ordered[date_column] = pd.to_datetime(ordered[date_column], errors="raise")
    ordered[metric] = pd.to_numeric(ordered[metric], errors="raise").astype(float)
    ordered = ordered.sort_values(date_column).reset_index(drop=True)
    if ordered[date_column].duplicated().any():
        raise ValueError("Forecast dates must be unique")
    if ordered[metric].isna().any() or not np.isfinite(ordered[metric]).all():
        raise ValueError("Forecast metric must contain finite non-missing values")
    if (ordered[metric] < 0).any():
        raise ValueError("Reference product metrics must be non-negative")

    required = season + origins * horizon_days + 1
    if len(ordered) < required:
        raise ValueError(
            f"Series needs at least {required} observations for {origins} origins, "
            f"{horizon_days}-day horizon and season {season}"
        )

    y = ordered[metric].reset_index(drop=True)
    dates = ordered[date_column].reset_index(drop=True)
    starts = list(range(len(y) - origins * horizon_days, len(y), horizon_days))
    rows: list[dict[str, object]] = []

    for origin_index, start in enumerate(starts, start=1):
        training = y.iloc[:start]
        calibration_residuals = (
            training.iloc[season:].to_numpy(dtype=float)
            - training.iloc[:-season].to_numpy(dtype=float)
        )
        radius = _finite_sample_absolute_residual_radius(calibration_residuals, interval_alpha)
        benchmark = float(training.iloc[-1])
        origin_date = dates.iloc[start - 1]

        for horizon_day in range(1, horizon_days + 1):
            target_index = start + horizon_day - 1
            source_index = target_index - season
            if source_index >= start:
                raise AssertionError("Seasonal source must be observable at forecast origin")
            point = float(y.iloc[source_index])
            actual = float(y.iloc[target_index])
            rows.append(
                {
                    "origin_index": origin_index,
                    "origin_date": origin_date.date().isoformat(),
                    "target_date": dates.iloc[target_index].date().isoformat(),
                    "seasonal_source_date": dates.iloc[source_index].date().isoformat(),
                    "horizon_day": horizon_day,
                    "actual": actual,
                    "forecast": point,
                    "benchmark_forecast": benchmark,
                    "interval_low": max(0.0, point - radius),
                    "interval_high": point + radius,
                    "interval_radius": radius,
                    "calibration_points": int(len(calibration_residuals)),
                }
            )
    return pd.DataFrame(rows)


def _mape(actual: pd.Series, forecast: pd.Series) -> float:
    denom = actual.abs().replace(0, np.nan)
    values = ((actual - forecast).abs() / denom).dropna()
    return float(values.mean()) if len(values) else float("nan")


def _wape(actual: pd.Series, forecast: pd.Series) -> float:
    denominator = float(actual.abs().sum())
    if denominator <= 0.0:
        return float("nan")
    return float((actual - forecast).abs().sum() / denominator)


def evaluate_forecast_plan(
    metric: str,
    backtest: pd.DataFrame,
    gate: ForecastPlanningGate = DEFAULT_FORECAST_PLANNING_GATE,
    *,
    interval_alpha: float = DEFAULT_INTERVAL_ALPHA,
) -> ForecastPlanningEvaluation:
    required = {
        "origin_index",
        "horizon_day",
        "actual",
        "forecast",
        "benchmark_forecast",
        "interval_low",
        "interval_high",
    }
    missing = required.difference(backtest.columns)
    if missing:
        raise ValueError(f"Missing forecast backtest columns: {sorted(missing)}")
    if backtest.empty:
        raise ValueError("Forecast backtest must be non-empty")

    actual = backtest["actual"].astype(float)
    forecast = backtest["forecast"].astype(float)
    benchmark = backtest["benchmark_forecast"].astype(float)
    mape = _mape(actual, forecast)
    wape = _wape(actual, forecast)
    benchmark_mape = _mape(actual, benchmark)
    benchmark_wape = _wape(actual, benchmark)
    relative_improvement = (
        float((benchmark_wape - wape) / benchmark_wape)
        if np.isfinite(benchmark_wape) and benchmark_wape > 0.0
        else float("nan")
    )
    coverage = float(
        (actual.ge(backtest["interval_low"].astype(float)) & actual.le(backtest["interval_high"].astype(float))).mean()
    )

    points = int(len(backtest))
    origins = int(backtest["origin_index"].nunique())
    horizon_days = int(backtest["horizon_day"].max())
    enough_gate = points >= gate.min_backtest_points
    accuracy_gate = bool(
        np.isfinite(mape)
        and np.isfinite(wape)
        and mape <= gate.max_mape
        and wape <= gate.max_wape
    )
    benchmark_gate = bool(
        not gate.require_noninferior_wape_to_benchmark
        or (
            np.isfinite(wape)
            and np.isfinite(benchmark_wape)
            and wape <= benchmark_wape + 1e-15
        )
    )
    interval_gate = bool(coverage >= gate.min_interval_coverage)
    approved = bool(enough_gate and accuracy_gate and benchmark_gate and interval_gate)

    failures: list[str] = []
    if not enough_gate:
        failures.append(f"backtest has {points} points; need {gate.min_backtest_points}")
    if not accuracy_gate:
        failures.append(
            f"absolute accuracy fails: MAPE {mape:.3f}, WAPE {wape:.3f}, limits {gate.max_mape:.3f}/{gate.max_wape:.3f}"
        )
    if not benchmark_gate:
        failures.append(f"candidate WAPE {wape:.3f} exceeds last-value benchmark {benchmark_wape:.3f}")
    if not interval_gate:
        failures.append(
            f"interval coverage {coverage:.3f} below {gate.min_interval_coverage:.3f}"
        )
    reason = "forecast eligible for planning" if approved else "; ".join(failures)

    return ForecastPlanningEvaluation(
        metric=metric,
        model="weekly_seasonal_naive_lag_7",
        benchmark="last_observation_carried_across_7d_horizon",
        origins=origins,
        horizon_days=horizon_days,
        backtest_points=points,
        mape=mape,
        wape=wape,
        benchmark_mape=benchmark_mape,
        benchmark_wape=benchmark_wape,
        relative_wape_improvement=relative_improvement,
        interval_nominal_coverage=1.0 - interval_alpha,
        interval_coverage=coverage,
        enough_backtest_gate=enough_gate,
        absolute_accuracy_gate=accuracy_gate,
        benchmark_gate=benchmark_gate,
        interval_coverage_gate=interval_gate,
        approved=approved,
        reason=reason,
    )


def forecast_reconciliation(metric: str, backtest: pd.DataFrame) -> pd.DataFrame:
    """Aggregate each historical 7-day plan against the outcomes later observed."""
    rows: list[dict[str, object]] = []
    for origin_index, frame in backtest.groupby("origin_index", sort=True):
        actual_total = float(frame["actual"].sum())
        planned_total = float(frame["forecast"].sum())
        benchmark_total = float(frame["benchmark_forecast"].sum())
        signed_error = planned_total - actual_total
        absolute_pct_error = (
            abs(signed_error) / abs(actual_total) if actual_total != 0.0 else float("nan")
        )
        rows.append(
            {
                "metric": metric,
                "origin_index": int(origin_index),
                "origin_date": str(frame["origin_date"].iloc[0]),
                "target_start_date": str(frame["target_date"].iloc[0]),
                "target_end_date": str(frame["target_date"].iloc[-1]),
                "planned_total": planned_total,
                "actual_total": actual_total,
                "benchmark_total": benchmark_total,
                "signed_error": signed_error,
                "absolute_pct_error": absolute_pct_error,
            }
        )
    return pd.DataFrame(rows)


def forecast_decision_contract(
    gate: ForecastPlanningGate = DEFAULT_FORECAST_PLANNING_GATE,
) -> dict[str, object]:
    return {
        "version": "2.0",
        "candidate_model": "weekly seasonal naive using lag-7 value",
        "benchmark_model": "last observation carried unchanged across each 7-day horizon",
        "season_days": DEFAULT_FORECAST_SEASON,
        "horizon_days": DEFAULT_FORECAST_HORIZON,
        "rolling_origins": DEFAULT_FORECAST_ORIGINS,
        "backtest_points_per_metric": DEFAULT_FORECAST_HORIZON * DEFAULT_FORECAST_ORIGINS,
        "interval_method": "symmetric absolute seasonal-residual conformal radius calibrated separately at each origin",
        "interval_nominal_coverage": 1.0 - DEFAULT_INTERVAL_ALPHA,
        "interval_order_statistic": "ceil((n + 1) * (1 - alpha)), capped at n",
        "planning_gate": asdict(gate),
        "decision_rule": "all backtest-depth, absolute-accuracy, benchmark and interval-coverage gates must pass",
        "weighted_score_used": False,
        "future_data_leakage_allowed": False,
        "seasonal_source_rule": "every target uses only its lag-7 value, which must be dated on or before the forecast origin",
        "reconciliation_rule": "each historical 7-day plan is compared with subsequently observed totals; aggregate interval coverage is not claimed by summing marginal intervals",
        "interpretation": "forecast eligibility is planning evidence for the synthetic reference, not a production SLA or claim about future realised accuracy",
    }
