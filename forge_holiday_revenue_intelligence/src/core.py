from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd
from sklearn.metrics import (
    average_precision_score,
    brier_score_loss,
    log_loss,
    mean_absolute_error,
    roc_auc_score,
)


LEAKAGE_COLUMNS = {
    "reservation_status",
    "reservation_status_date",
    "assigned_room_type",
    "booking_changes",
    "days_in_waiting_list",
}

MONTH_MAP = {
    "January": 1,
    "February": 2,
    "March": 3,
    "April": 4,
    "May": 5,
    "June": 6,
    "July": 7,
    "August": 8,
    "September": 9,
    "October": 10,
    "November": 11,
    "December": 12,
}


def parse_money(value: object) -> float:
    """Parse common currency strings such as '$1,234.50' into floats."""
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return float("nan")
    if isinstance(value, (int, float, np.number)):
        return float(value)
    cleaned = re.sub(r"[^0-9.\-]", "", str(value))
    return float(cleaned) if cleaned not in {"", ".", "-"} else float("nan")


def arrival_date(df: pd.DataFrame) -> pd.Series:
    month = df["arrival_date_month"].map(MONTH_MAP)
    return pd.to_datetime(
        {
            "year": pd.to_numeric(df["arrival_date_year"], errors="coerce"),
            "month": month,
            "day": pd.to_numeric(df["arrival_date_day_of_month"], errors="coerce"),
        },
        errors="coerce",
    )


def safe_auc(y_true: Iterable[int], y_score: Iterable[float]) -> float:
    y = np.asarray(list(y_true))
    score = np.asarray(list(y_score))
    if len(np.unique(y)) < 2:
        return float("nan")
    return float(roc_auc_score(y, score))


def classification_metrics(y_true: pd.Series, p: np.ndarray) -> dict[str, float]:
    y = np.asarray(y_true, dtype=int)
    p = np.clip(np.asarray(p, dtype=float), 1e-6, 1 - 1e-6)
    return {
        "roc_auc": safe_auc(y, p),
        "average_precision": float(average_precision_score(y, p)),
        "brier": float(brier_score_loss(y, p)),
        "log_loss": float(log_loss(y, p)),
    }


def top_fraction_metrics(
    y_true: pd.Series,
    p: np.ndarray,
    exposure: pd.Series,
    fraction: float = 0.10,
) -> dict[str, float]:
    frame = pd.DataFrame(
        {
            "y": np.asarray(y_true, dtype=int),
            "p": np.asarray(p, dtype=float),
            "exposure": np.asarray(exposure, dtype=float),
        }
    ).sort_values("p", ascending=False)
    n = max(1, int(math.ceil(len(frame) * fraction)))
    top = frame.head(n)
    cancelled_exposure = float((frame["exposure"] * frame["y"]).sum())
    captured = float((top["exposure"] * top["y"]).sum())
    return {
        "review_fraction": n / len(frame),
        "top_cancel_rate": float(top["y"].mean()),
        "overall_cancel_rate": float(frame["y"].mean()),
        "cancelled_exposure_capture": captured / cancelled_exposure
        if cancelled_exposure > 0
        else float("nan"),
    }


def population_stability_index(
    reference: pd.Series,
    current: pd.Series,
    bins: int = 10,
) -> float:
    """Population stability index using reference quantile bins."""
    ref = pd.to_numeric(reference, errors="coerce").dropna().to_numpy()
    cur = pd.to_numeric(current, errors="coerce").dropna().to_numpy()
    if len(ref) == 0 or len(cur) == 0:
        return float("nan")
    cuts = np.unique(np.quantile(ref, np.linspace(0, 1, bins + 1)))
    if len(cuts) < 3:
        return 0.0
    cuts[0] = -np.inf
    cuts[-1] = np.inf
    ref_hist, _ = np.histogram(ref, bins=cuts)
    cur_hist, _ = np.histogram(cur, bins=cuts)
    eps = 1e-6
    ref_share = np.clip(ref_hist / max(ref_hist.sum(), 1), eps, 1)
    cur_share = np.clip(cur_hist / max(cur_hist.sum(), 1), eps, 1)
    return float(np.sum((cur_share - ref_share) * np.log(cur_share / ref_share)))


def wape(y_true: Iterable[float], y_pred: Iterable[float]) -> float:
    y = np.asarray(list(y_true), dtype=float)
    p = np.asarray(list(y_pred), dtype=float)
    denom = np.abs(y).sum()
    return float(np.abs(y - p).sum() / denom) if denom > 0 else float("nan")


def regression_metrics(y_true: Iterable[float], y_pred: Iterable[float]) -> dict[str, float]:
    y = np.asarray(list(y_true), dtype=float)
    p = np.asarray(list(y_pred), dtype=float)
    return {
        "mae": float(mean_absolute_error(y, p)),
        "wape": wape(y, p),
    }


def assert_no_leakage(features: Iterable[str]) -> None:
    overlap = LEAKAGE_COLUMNS.intersection(set(features))
    if overlap:
        raise ValueError(f"Leakage columns present in model features: {sorted(overlap)}")


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n")
