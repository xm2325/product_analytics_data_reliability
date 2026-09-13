from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor
from sklearn.impute import SimpleImputer
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, OrdinalEncoder

from core import (
    arrival_date,
    assert_no_leakage,
    classification_metrics,
    parse_money,
    population_stability_index,
    regression_metrics,
    top_fraction_metrics,
    write_json,
)

HOTEL_URL = (
    "https://raw.githubusercontent.com/rfordatascience/tidytuesday/main/"
    "data/2020/2020-02-11/hotels.csv"
)
GM_LISTINGS_URL = (
    "https://data.insideairbnb.com/united-kingdom/england/greater-manchester/"
    "2024-12-25/data/listings.csv.gz"
)
GM_CALENDAR_URL = (
    "https://data.insideairbnb.com/united-kingdom/england/greater-manchester/"
    "2024-12-25/data/calendar.csv.gz"
)

NUMERIC_FEATURES = [
    "lead_time",
    "arrival_date_week_number",
    "arrival_date_day_of_month",
    "stays_in_weekend_nights",
    "stays_in_week_nights",
    "adults",
    "children",
    "babies",
    "is_repeated_guest",
    "previous_cancellations",
    "previous_bookings_not_canceled",
    "average_daily_rate",
    "required_car_parking_spaces",
    "total_of_special_requests",
]

CATEGORICAL_FEATURES = [
    "hotel",
    "arrival_date_month",
    "meal",
    "country",
    "market_segment",
    "distribution_channel",
    "reserved_room_type",
    "deposit_type",
    "customer_type",
]

PRICE_NUMERIC_FEATURES = [c for c in NUMERIC_FEATURES if c != "average_daily_rate"]
PRICE_CATEGORICAL_FEATURES = CATEGORICAL_FEATURES


def load_hotel_data() -> pd.DataFrame:
    print(f"DATA_SOURCE hotel={HOTEL_URL}")
    df = pd.read_csv(HOTEL_URL, low_memory=False)
    if "adr" in df.columns and "average_daily_rate" not in df.columns:
        df = df.rename(columns={"adr": "average_daily_rate"})
    required = {
        "hotel",
        "is_canceled",
        "lead_time",
        "arrival_date_year",
        "arrival_date_month",
        "arrival_date_day_of_month",
        "average_daily_rate",
        "reservation_status",
        "reservation_status_date",
    }
    missing = required.difference(df.columns)
    if missing:
        raise ValueError(f"Hotel dataset is missing required columns: {sorted(missing)}")
    df["arrival_date"] = arrival_date(df)
    df["children"] = pd.to_numeric(df["children"], errors="coerce")
    df["total_nights"] = (
        pd.to_numeric(df["stays_in_weekend_nights"], errors="coerce").fillna(0)
        + pd.to_numeric(df["stays_in_week_nights"], errors="coerce").fillna(0)
    )
    df["gross_booking_value"] = (
        pd.to_numeric(df["average_daily_rate"], errors="coerce").clip(lower=0)
        * df["total_nights"].clip(lower=0)
    )
    df = df[df["arrival_date"].notna()].copy()
    print(
        "HOTEL_DATA rows={} date_min={} date_max={} cancel_rate={:.4f}".format(
            len(df),
            df["arrival_date"].min().date(),
            df["arrival_date"].max().date(),
            df["is_canceled"].mean(),
        )
    )
    return df


def split_hotel_data(df: pd.DataFrame):
    train_end = pd.Timestamp("2016-10-01")
    test_start = pd.Timestamp("2017-01-01")
    train = df[df["arrival_date"] < train_end].copy()
    calib = df[(df["arrival_date"] >= train_end) & (df["arrival_date"] < test_start)].copy()
    test = df[df["arrival_date"] >= test_start].copy()
    if min(len(train), len(calib), len(test)) == 0:
        raise ValueError("Temporal split produced an empty partition")
    print(f"TEMPORAL_SPLIT train={len(train)} calibration={len(calib)} test={len(test)}")
    return train, calib, test


def make_logistic_pipeline() -> Pipeline:
    numeric = Pipeline([("impute", SimpleImputer(strategy="median"))])
    categorical = Pipeline(
        [
            ("impute", SimpleImputer(strategy="most_frequent")),
            (
                "onehot",
                OneHotEncoder(
                    handle_unknown="ignore",
                    min_frequency=20,
                    sparse_output=True,
                ),
            ),
        ]
    )
    prep = ColumnTransformer(
        [("num", numeric, NUMERIC_FEATURES), ("cat", categorical, CATEGORICAL_FEATURES)],
        remainder="drop",
    )
    return Pipeline(
        [
            ("prep", prep),
            ("model", LogisticRegression(max_iter=600, solver="liblinear")),
        ]
    )


def make_hgb_classifier() -> Pipeline:
    numeric = Pipeline([("impute", SimpleImputer(strategy="median"))])
    categorical = Pipeline(
        [
            ("impute", SimpleImputer(strategy="most_frequent")),
            (
                "ordinal",
                OrdinalEncoder(
                    handle_unknown="use_encoded_value",
                    unknown_value=-1,
                    encoded_missing_value=-1,
                    max_categories=250,
                ),
            ),
        ]
    )
    prep = ColumnTransformer(
        [("num", numeric, NUMERIC_FEATURES), ("cat", categorical, CATEGORICAL_FEATURES)],
        remainder="drop",
    )
    cat_idx = list(range(len(NUMERIC_FEATURES), len(NUMERIC_FEATURES) + len(CATEGORICAL_FEATURES)))
    model = HistGradientBoostingClassifier(
        learning_rate=0.06,
        max_iter=220,
        max_leaf_nodes=31,
        l2_regularization=1.0,
        categorical_features=cat_idx,
        random_state=42,
    )
    return Pipeline([("prep", prep), ("model", model)])


def fit_isotonic(raw_calib: np.ndarray, y_calib: pd.Series, raw_test: np.ndarray) -> np.ndarray:
    calibrator = IsotonicRegression(out_of_bounds="clip")
    calibrator.fit(raw_calib, np.asarray(y_calib, dtype=int))
    return np.clip(calibrator.predict(raw_test), 1e-6, 1 - 1e-6)


def run_cancellation_model(df: pd.DataFrame) -> dict:
    assert_no_leakage(NUMERIC_FEATURES + CATEGORICAL_FEATURES)
    train, calib, test = split_hotel_data(df)
    y_train = train["is_canceled"].astype(int)
    y_calib = calib["is_canceled"].astype(int)
    y_test = test["is_canceled"].astype(int)

    constant = np.full(len(test), float(y_train.mean()))
    results: dict[str, dict] = {
        "constant_rate": classification_metrics(y_test, constant)
    }
    models = {
        "logistic_regression": make_logistic_pipeline(),
        "hist_gradient_boosting": make_hgb_classifier(),
    }
    calibrated_predictions: dict[str, np.ndarray] = {}
    calibration_metrics: dict[str, dict] = {}

    for name, model in models.items():
        print(f"FIT cancellation_model={name}")
        model.fit(train, y_train)
        p_calib_raw = model.predict_proba(calib)[:, 1]
        p_test_raw = model.predict_proba(test)[:, 1]
        p_test = fit_isotonic(p_calib_raw, y_calib, p_test_raw)
        p_calib = fit_isotonic(p_calib_raw, y_calib, p_calib_raw)
        results[name] = classification_metrics(y_test, p_test)
        calibration_metrics[name] = classification_metrics(y_calib, p_calib)
        calibrated_predictions[name] = p_test

    baseline_name = "logistic_regression"
    challenger_name = "hist_gradient_boosting"
    base = results[baseline_name]
    chall = results[challenger_name]
    promote = (
        chall["average_precision"] >= base["average_precision"] + 0.01
        and chall["brier"] <= base["brier"] + 0.005
    )
    champion = challenger_name if promote else baseline_name
    p_champion = calibrated_predictions[champion]

    exposure = test["gross_booking_value"].fillna(0).clip(lower=0)
    top_risk = top_fraction_metrics(y_test, p_champion, exposure, fraction=0.10)
    observed_realised = float((exposure * (1 - y_test.to_numpy())).sum())
    predicted_realised = float((exposure * (1 - p_champion)).sum())
    revenue_error_pct = (
        (predicted_realised - observed_realised) / observed_realised
        if observed_realised > 0
        else float("nan")
    )

    monthly = pd.DataFrame(
        {
            "arrival_date": test["arrival_date"].to_numpy(),
            "is_canceled": y_test.to_numpy(),
            "p_cancel": p_champion,
        }
    )
    monthly["month"] = monthly["arrival_date"].dt.to_period("M").astype(str)
    monthly_summary = (
        monthly.groupby("month")
        .agg(actual_cancel_rate=("is_canceled", "mean"), predicted_cancel_rate=("p_cancel", "mean"), n=("is_canceled", "size"))
        .reset_index()
    )

    drift_features = ["lead_time", "average_daily_rate", "total_nights", "total_of_special_requests", "previous_cancellations"]
    drift = {
        feature: population_stability_index(train[feature], test[feature])
        for feature in drift_features
    }
    max_psi = max(v for v in drift.values() if not np.isnan(v))
    calib_brier = calibration_metrics[champion]["brier"]
    test_brier = results[champion]["brier"]
    retrain_flag = bool(max_psi > 0.20 or test_brier > calib_brier + 0.02)

    return {
        "sample_sizes": {"train": len(train), "calibration": len(calib), "test": len(test)},
        "metrics": results,
        "calibration_period_metrics": calibration_metrics,
        "promotion_gate": {
            "rule": "promote challenger only if AP improves by >=0.01 and Brier worsens by no more than 0.005",
            "challenger_promoted": promote,
            "champion": champion,
        },
        "top_10pct_risk": top_risk,
        "revenue_reliability": {
            "observed_non_cancelled_gross_value_proxy": observed_realised,
            "predicted_non_cancelled_gross_value_proxy": predicted_realised,
            "relative_error": revenue_error_pct,
        },
        "drift": {
            "psi": drift,
            "max_psi": max_psi,
            "calibration_brier": calib_brier,
            "test_brier": test_brier,
            "retrain_review_flag": retrain_flag,
        },
        "monthly": monthly_summary.to_dict(orient="records"),
    }


def make_price_model(quantile: float) -> Pipeline:
    numeric = Pipeline([("impute", SimpleImputer(strategy="median"))])
    categorical = Pipeline(
        [
            ("impute", SimpleImputer(strategy="most_frequent")),
            (
                "ordinal",
                OrdinalEncoder(
                    handle_unknown="use_encoded_value",
                    unknown_value=-1,
                    encoded_missing_value=-1,
                    max_categories=250,
                ),
            ),
        ]
    )
    prep = ColumnTransformer(
        [("num", numeric, PRICE_NUMERIC_FEATURES), ("cat", categorical, PRICE_CATEGORICAL_FEATURES)],
        remainder="drop",
    )
    cat_idx = list(
        range(
            len(PRICE_NUMERIC_FEATURES),
            len(PRICE_NUMERIC_FEATURES) + len(PRICE_CATEGORICAL_FEATURES),
        )
    )
    model = HistGradientBoostingRegressor(
        loss="quantile",
        quantile=quantile,
        learning_rate=0.06,
        max_iter=180,
        max_leaf_nodes=31,
        l2_regularization=1.0,
        categorical_features=cat_idx,
        random_state=42,
    )
    return Pipeline([("prep", prep), ("model", model)])


def run_price_benchmark(df: pd.DataFrame) -> dict:
    assert_no_leakage(PRICE_NUMERIC_FEATURES + PRICE_CATEGORICAL_FEATURES)
    completed = df[(df["is_canceled"] == 0) & (df["average_daily_rate"] > 0) & (df["average_daily_rate"] < 1000)].copy()
    train, _, test = split_hotel_data(completed)
    y_train = train["average_daily_rate"].astype(float)
    y_test = test["average_daily_rate"].astype(float)

    preds: dict[float, np.ndarray] = {}
    for q in (0.25, 0.50, 0.75):
        print(f"FIT price_quantile={q}")
        model = make_price_model(q)
        model.fit(train, y_train)
        preds[q] = model.predict(test)

    q25 = preds[0.25]
    q50 = preds[0.50]
    q75 = preds[0.75]
    lower = np.minimum(q25, q75)
    upper = np.maximum(q25, q75)
    coverage = float(np.mean((y_test.to_numpy() >= lower) & (y_test.to_numpy() <= upper)))
    band = np.where(y_test.to_numpy() < lower, "below_reference", np.where(y_test.to_numpy() > upper, "above_reference", "within_reference_band"))
    band_share = pd.Series(band).value_counts(normalize=True).to_dict()

    return {
        "completed_stay_rows": int(len(completed)),
        "train_rows": int(len(train)),
        "test_rows": int(len(test)),
        "median_model": regression_metrics(y_test, q50),
        "central_50pct_interval_coverage": coverage,
        "observed_price_position_share": {k: float(v) for k, v in band_share.items()},
        "interpretation": "The price model is a comparable-booking reference band. It is not a causal estimate of price elasticity or an optimal-price claim.",
    }


def run_weekly_demand_forecast(df: pd.DataFrame) -> dict:
    completed = df[df["is_canceled"] == 0].copy()
    completed["room_nights"] = completed["total_nights"].clip(lower=0)
    completed["week"] = completed["arrival_date"].dt.to_period("W-MON").dt.start_time
    weekly = completed.groupby("week", as_index=False).agg(
        room_nights=("room_nights", "sum"),
        completed_bookings=("is_canceled", "size"),
    )
    all_weeks = pd.date_range(weekly["week"].min(), weekly["week"].max(), freq="7D")
    weekly = weekly.set_index("week").reindex(all_weeks).fillna(0).rename_axis("week").reset_index()
    y = weekly["room_nights"].astype(float)
    for lag in (1, 2, 4, 13, 52):
        weekly[f"lag_{lag}"] = y.shift(lag)
    weekly["roll_4"] = y.shift(1).rolling(4).mean()
    weekly["roll_13"] = y.shift(1).rolling(13).mean()
    weekly["trend"] = np.arange(len(weekly))
    iso = weekly["week"].dt.isocalendar().week.astype(int)
    weekly["week_sin"] = np.sin(2 * np.pi * iso / 52.18)
    weekly["week_cos"] = np.cos(2 * np.pi * iso / 52.18)

    features = ["lag_1", "lag_2", "lag_4", "lag_13", "lag_52", "roll_4", "roll_13", "trend", "week_sin", "week_cos"]
    eligible = weekly.dropna(subset=features).copy()
    train = eligible[eligible["week"] < pd.Timestamp("2017-01-01")]
    test = eligible[eligible["week"] >= pd.Timestamp("2017-01-01")]
    if len(train) < 20 or len(test) < 10:
        raise ValueError(f"Insufficient weekly rows after lagging: train={len(train)}, test={len(test)}")

    model = HistGradientBoostingRegressor(
        learning_rate=0.05,
        max_iter=180,
        max_leaf_nodes=15,
        l2_regularization=2.0,
        random_state=42,
    )
    model.fit(train[features], train["room_nights"])
    pred = np.clip(model.predict(test[features]), 0, None)
    seasonal = np.clip(test["lag_52"].to_numpy(), 0, None)
    rolling = np.clip(test["roll_4"].to_numpy(), 0, None)

    metrics = {
        "seasonal_naive_lag52": regression_metrics(test["room_nights"], seasonal),
        "rolling_4_week": regression_metrics(test["room_nights"], rolling),
        "hist_gradient_boosting": regression_metrics(test["room_nights"], pred),
    }
    best_baseline_wape = min(metrics["seasonal_naive_lag52"]["wape"], metrics["rolling_4_week"]["wape"])
    model_wape = metrics["hist_gradient_boosting"]["wape"]
    promote = bool(model_wape < best_baseline_wape * 0.98)
    return {
        "target": "one-week-ahead completed room-nights, evaluated with rolling observed lags",
        "train_weeks": int(len(train)),
        "test_weeks": int(len(test)),
        "metrics": metrics,
        "promotion_gate": {
            "rule": "promote only if WAPE improves by at least 2% relative to the best simple baseline",
            "model_promoted": promote,
        },
    }


def run_inside_airbnb_market() -> dict:
    print(f"DATA_SOURCE inside_airbnb_listings={GM_LISTINGS_URL}")
    print(f"DATA_SOURCE inside_airbnb_calendar={GM_CALENDAR_URL}")
    listings = pd.read_csv(GM_LISTINGS_URL, compression="gzip", low_memory=False)
    calendar = pd.read_csv(
        GM_CALENDAR_URL,
        compression="gzip",
        usecols=["listing_id", "date", "available", "price", "minimum_nights"],
        low_memory=False,
    )
    calendar["date"] = pd.to_datetime(calendar["date"], errors="coerce")
    calendar["price_value"] = calendar["price"].map(parse_money)
    calendar["is_available"] = calendar["available"].astype(str).str.lower().eq("t")
    calendar = calendar[calendar["date"].notna() & calendar["price_value"].between(1, 5000)].copy()
    snapshot_date = pd.Timestamp("2024-12-25")
    window = calendar[(calendar["date"] >= snapshot_date) & (calendar["date"] < snapshot_date + pd.Timedelta(days=180))].copy()
    window["week"] = window["date"].dt.to_period("W-MON").dt.start_time
    weekly = window.groupby("week").agg(
        listing_days=("listing_id", "size"),
        distinct_listings=("listing_id", "nunique"),
        availability_rate=("is_available", "mean"),
        median_asking_price=("price_value", "median"),
        p25_asking_price=("price_value", lambda s: s.quantile(0.25)),
        p75_asking_price=("price_value", lambda s: s.quantile(0.75)),
    ).reset_index()
    q25_avail = float(weekly["availability_rate"].quantile(0.25))
    q75_avail = float(weekly["availability_rate"].quantile(0.75))
    tight = weekly[weekly["availability_rate"] <= q25_avail]
    loose = weekly[weekly["availability_rate"] >= q75_avail]
    tight_price = float(tight["median_asking_price"].median())
    loose_price = float(loose["median_asking_price"].median())
    price_diff_pct = tight_price / loose_price - 1 if loose_price > 0 else float("nan")

    return {
        "snapshot": "Greater Manchester, 2024-12-25 Inside Airbnb public snapshot",
        "listings_rows": int(len(listings)),
        "calendar_rows_loaded": int(len(calendar)),
        "analysis_window_days": 180,
        "analysis_listing_days": int(len(window)),
        "weekly_periods": int(len(weekly)),
        "availability_rate_min": float(weekly["availability_rate"].min()),
        "availability_rate_max": float(weekly["availability_rate"].max()),
        "median_weekly_asking_price": float(weekly["median_asking_price"].median()),
        "tight_availability_threshold": q25_avail,
        "loose_availability_threshold": q75_avail,
        "tight_weeks_median_asking_price": tight_price,
        "loose_weeks_median_asking_price": loose_price,
        "tight_vs_loose_price_difference_pct": price_diff_pct,
        "caveat": "available=False is not treated as a confirmed booking. Availability is used only as a market-supply/availability-pressure proxy.",
        "weekly": weekly.assign(week=weekly["week"].astype(str)).to_dict(orient="records"),
    }


def executive_summary(metrics: dict) -> str:
    cancel = metrics["cancellation"]
    champion = cancel["promotion_gate"]["champion"]
    cm = cancel["metrics"][champion]
    demand = metrics["demand_forecast"]
    price = metrics["price_benchmark"]
    uk = metrics.get("uk_market")
    lines = [
        "# Executive summary",
        "",
        "This is a real-data accommodation analytics case study designed around holiday-rental commercial questions: demand forecasting, cancellation-aware revenue reliability, comparable-market pricing and production monitoring.",
        "",
        f"The cancellation champion is **{champion}** on a future-arrival holdout, with ROC-AUC **{cm['roc_auc']:.3f}**, average precision **{cm['average_precision']:.3f}** and Brier score **{cm['brier']:.3f}**.",
        f"The top-risk 10% of test bookings has cancellation rate **{cancel['top_10pct_risk']['top_cancel_rate']:.1%}** versus **{cancel['top_10pct_risk']['overall_cancel_rate']:.1%}** overall, while capturing **{cancel['top_10pct_risk']['cancelled_exposure_capture']:.1%}** of cancelled gross-value exposure.",
        f"The comparable-booking median price model has MAE **{price['median_model']['mae']:.2f}** in the source dataset's ADR units; the central 50% reference interval covers **{price['central_50pct_interval_coverage']:.1%}** of future completed stays.",
        f"The weekly demand model WAPE is **{demand['metrics']['hist_gradient_boosting']['wape']:.1%}** versus **{demand['metrics']['seasonal_naive_lag52']['wape']:.1%}** for the seasonal-naive baseline and **{demand['metrics']['rolling_4_week']['wape']:.1%}** for the rolling-mean baseline.",
    ]
    if uk:
        lines.extend(
            [
                f"The UK market module uses **{uk['analysis_listing_days']:,} listing-days** from a Greater Manchester Inside Airbnb snapshot. Across the 180-day forward window, weekly availability ranges from **{uk['availability_rate_min']:.1%}** to **{uk['availability_rate_max']:.1%}** and the median weekly asking price is **£{uk['median_weekly_asking_price']:.0f}**.",
                "Inside Airbnb unavailable dates are not labelled as bookings; they are used only as an availability-pressure proxy.",
            ]
        )
    lines.extend(
        [
            "",
            "## Decision boundary",
            "",
            "The pricing component is a comparable-booking reference band, not a causal price-elasticity model. No claim is made that changing a quoted price would cause the observed revenue response. Production promotion is controlled by explicit model and drift gates.",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", default="reports/generated")
    args = parser.parse_args()
    out = Path(args.output_dir)
    out.mkdir(parents=True, exist_ok=True)

    hotel = load_hotel_data()
    metrics: dict = {
        "data": {
            "hotel_rows": int(len(hotel)),
            "hotel_date_min": str(hotel["arrival_date"].min().date()),
            "hotel_date_max": str(hotel["arrival_date"].max().date()),
            "hotel_cancel_rate": float(hotel["is_canceled"].mean()),
        },
        "cancellation": run_cancellation_model(hotel),
        "price_benchmark": run_price_benchmark(hotel),
        "demand_forecast": run_weekly_demand_forecast(hotel),
    }

    try:
        metrics["uk_market"] = run_inside_airbnb_market()
        metrics["uk_market_status"] = "success"
    except Exception as exc:  # UK module is additive; core real-booking analysis still runs.
        metrics["uk_market_status"] = f"failed: {type(exc).__name__}: {exc}"
        print(f"UK_MARKET_WARNING {metrics['uk_market_status']}", file=sys.stderr)

    write_json(out / "metrics.json", metrics)
    (out / "executive_summary.md").write_text(executive_summary(metrics))

    print("FORGE_METRICS_JSON_START")
    print(json.dumps(metrics, indent=2, sort_keys=True, default=str))
    print("FORGE_METRICS_JSON_END")
    print(executive_summary(metrics))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
