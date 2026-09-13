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
from sklearn.linear_model import LogisticRegression, Ridge
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, OrdinalEncoder, StandardScaler

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
    df["lead_time"] = pd.to_numeric(df["lead_time"], errors="coerce")
    df["booking_date"] = df["arrival_date"] - pd.to_timedelta(df["lead_time"], unit="D")
    df["children"] = pd.to_numeric(df["children"], errors="coerce")
    df["total_nights"] = (
        pd.to_numeric(df["stays_in_weekend_nights"], errors="coerce").fillna(0)
        + pd.to_numeric(df["stays_in_week_nights"], errors="coerce").fillna(0)
    )
    df["gross_booking_value"] = (
        pd.to_numeric(df["average_daily_rate"], errors="coerce").clip(lower=0)
        * df["total_nights"].clip(lower=0)
    )
    df = df[df["arrival_date"].notna() & df["booking_date"].notna()].copy()
    print(
        "HOTEL_DATA rows={} arrival_min={} arrival_max={} booking_min={} booking_max={} cancel_rate={:.4f}".format(
            len(df),
            df["arrival_date"].min().date(),
            df["arrival_date"].max().date(),
            df["booking_date"].min().date(),
            df["booking_date"].max().date(),
            df["is_canceled"].mean(),
        )
    )
    return df


def split_by_booking_date(df: pd.DataFrame):
    """Four-way point-in-time split using the inferred booking creation date."""
    train_end = pd.Timestamp("2016-07-01")
    calibration_end = pd.Timestamp("2016-10-01")
    validation_end = pd.Timestamp("2017-01-01")

    train = df[df["booking_date"] < train_end].copy()
    calibration = df[
        (df["booking_date"] >= train_end) & (df["booking_date"] < calibration_end)
    ].copy()
    validation = df[
        (df["booking_date"] >= calibration_end)
        & (df["booking_date"] < validation_end)
    ].copy()
    test = df[df["booking_date"] >= validation_end].copy()

    if min(len(train), len(calibration), len(validation), len(test)) == 0:
        raise ValueError("Point-in-time split produced an empty partition")
    print(
        "BOOKING_TIME_SPLIT train={} calibration={} validation={} test={}".format(
            len(train), len(calibration), len(validation), len(test)
        )
    )
    return train, calibration, validation, test


def make_logistic_pipeline(categorical_features: list[str] | None = None) -> Pipeline:
    categorical_features = categorical_features or CATEGORICAL_FEATURES
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
        [("num", numeric, NUMERIC_FEATURES), ("cat", categorical, categorical_features)],
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
    cat_idx = list(
        range(len(NUMERIC_FEATURES), len(NUMERIC_FEATURES) + len(CATEGORICAL_FEATURES))
    )
    model = HistGradientBoostingClassifier(
        learning_rate=0.06,
        max_iter=220,
        max_leaf_nodes=31,
        l2_regularization=1.0,
        categorical_features=cat_idx,
        random_state=42,
    )
    return Pipeline([("prep", prep), ("model", model)])


def fit_isotonic(
    raw_calibration: np.ndarray,
    y_calibration: pd.Series,
    raw_target: np.ndarray,
) -> np.ndarray:
    calibrator = IsotonicRegression(out_of_bounds="clip")
    calibrator.fit(raw_calibration, np.asarray(y_calibration, dtype=int))
    return np.clip(calibrator.predict(raw_target), 1e-6, 1 - 1e-6)


def run_cancellation_model(df: pd.DataFrame) -> dict:
    assert_no_leakage(NUMERIC_FEATURES + CATEGORICAL_FEATURES)
    train, calibration, validation, test = split_by_booking_date(df)
    y_train = train["is_canceled"].astype(int)
    y_calibration = calibration["is_canceled"].astype(int)
    y_validation = validation["is_canceled"].astype(int)
    y_test = test["is_canceled"].astype(int)

    test_metrics: dict[str, dict] = {
        "constant_rate": classification_metrics(
            y_test, np.full(len(test), float(y_train.mean()))
        )
    }
    validation_metrics: dict[str, dict] = {}
    test_predictions: dict[str, np.ndarray] = {}

    models = {
        "logistic_regression": make_logistic_pipeline(),
        "hist_gradient_boosting": make_hgb_classifier(),
    }
    for name, model in models.items():
        print(f"FIT cancellation_model={name}")
        model.fit(train, y_train)
        p_calibration_raw = model.predict_proba(calibration)[:, 1]
        p_validation_raw = model.predict_proba(validation)[:, 1]
        p_test_raw = model.predict_proba(test)[:, 1]
        p_validation = fit_isotonic(
            p_calibration_raw, y_calibration, p_validation_raw
        )
        p_test = fit_isotonic(p_calibration_raw, y_calibration, p_test_raw)
        validation_metrics[name] = classification_metrics(y_validation, p_validation)
        test_metrics[name] = classification_metrics(y_test, p_test)
        test_predictions[name] = p_test

    baseline_name = "logistic_regression"
    challenger_name = "hist_gradient_boosting"
    baseline_validation = validation_metrics[baseline_name]
    challenger_validation = validation_metrics[challenger_name]
    promote_challenger = (
        challenger_validation["average_precision"]
        >= baseline_validation["average_precision"] + 0.01
        and challenger_validation["brier"] <= baseline_validation["brier"] + 0.005
    )
    champion = challenger_name if promote_challenger else baseline_name
    p_champion = test_predictions[champion]

    no_deposit_categories = [c for c in CATEGORICAL_FEATURES if c != "deposit_type"]
    no_deposit = make_logistic_pipeline(no_deposit_categories)
    no_deposit.fit(train, y_train)
    p_calibration_nd_raw = no_deposit.predict_proba(calibration)[:, 1]
    p_validation_nd = fit_isotonic(
        p_calibration_nd_raw,
        y_calibration,
        no_deposit.predict_proba(validation)[:, 1],
    )
    p_test_nd = fit_isotonic(
        p_calibration_nd_raw,
        y_calibration,
        no_deposit.predict_proba(test)[:, 1],
    )
    no_deposit_validation_metrics = classification_metrics(y_validation, p_validation_nd)
    no_deposit_test_metrics = classification_metrics(y_test, p_test_nd)

    exposure = test["gross_booking_value"].fillna(0).clip(lower=0)
    top_risk = top_fraction_metrics(y_test, p_champion, exposure, fraction=0.10)
    top_risk_no_deposit = top_fraction_metrics(
        y_test, p_test_nd, exposure, fraction=0.10
    )

    observed_realised = float((exposure * (1 - y_test.to_numpy())).sum())
    predicted_realised = float((exposure * (1 - p_champion)).sum())
    revenue_error_pct = (
        (predicted_realised - observed_realised) / observed_realised
        if observed_realised > 0
        else float("nan")
    )

    monthly = pd.DataFrame(
        {
            "booking_date": test["booking_date"].to_numpy(),
            "is_canceled": y_test.to_numpy(),
            "p_cancel": p_champion,
        }
    )
    monthly["month"] = monthly["booking_date"].dt.to_period("M").astype(str)
    monthly_summary = (
        monthly.groupby("month")
        .agg(
            actual_cancel_rate=("is_canceled", "mean"),
            predicted_cancel_rate=("p_cancel", "mean"),
            n=("is_canceled", "size"),
        )
        .reset_index()
    )

    drift_features = [
        "lead_time",
        "average_daily_rate",
        "total_nights",
        "total_of_special_requests",
        "previous_cancellations",
    ]
    drift = {
        feature: population_stability_index(validation[feature], test[feature])
        for feature in drift_features
    }
    valid_psi = [v for v in drift.values() if not np.isnan(v)]
    max_psi = max(valid_psi) if valid_psi else float("nan")
    validation_brier = validation_metrics[champion]["brier"]
    test_brier = test_metrics[champion]["brier"]
    brier_degradation = test_brier - validation_brier
    retrain_flag = bool(
        (not np.isnan(max_psi) and max_psi > 0.15)
        or brier_degradation > 0.015
        or abs(revenue_error_pct) > 0.05
    )

    return {
        "time_axis": "booking_date = arrival_date - lead_time; no test-period observations are used for model selection",
        "sample_sizes": {
            "train": len(train),
            "calibration": len(calibration),
            "validation": len(validation),
            "test": len(test),
        },
        "validation_metrics": validation_metrics,
        "test_metrics": test_metrics,
        "promotion_gate": {
            "selection_period": "validation only",
            "rule": "promote challenger only if validation AP improves by >=0.01 and validation Brier worsens by no more than 0.005",
            "challenger_promoted": promote_challenger,
            "champion": champion,
        },
        "policy_feature_ablation": {
            "feature_removed": "deposit_type",
            "validation_metrics": no_deposit_validation_metrics,
            "test_metrics": no_deposit_test_metrics,
            "full_minus_no_deposit_test_average_precision": (
                test_metrics[baseline_name]["average_precision"]
                - no_deposit_test_metrics["average_precision"]
            ),
            "top_10pct_without_deposit": top_risk_no_deposit,
            "interpretation": "Deposit type is available at booking time but can encode a commercial policy. This ablation checks how much apparent predictive strength depends on that policy-sensitive field.",
        },
        "top_10pct_risk": top_risk,
        "revenue_reliability": {
            "observed_non_cancelled_gross_value_proxy": observed_realised,
            "predicted_non_cancelled_gross_value_proxy": predicted_realised,
            "relative_error": revenue_error_pct,
        },
        "drift": {
            "reference_period": "validation",
            "psi": drift,
            "max_psi": max_psi,
            "validation_brier": validation_brier,
            "test_brier": test_brier,
            "brier_degradation": brier_degradation,
            "review_gate": "flag if max PSI > 0.15, Brier worsens by >0.015, or cancellation-adjusted gross-value proxy error exceeds 5%",
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


def finite_sample_quantile(values: np.ndarray, coverage: float) -> float:
    values = np.sort(np.asarray(values, dtype=float))
    if len(values) == 0:
        return 0.0
    rank = int(np.ceil((len(values) + 1) * coverage)) - 1
    rank = min(max(rank, 0), len(values) - 1)
    return float(values[rank])


def run_price_benchmark(df: pd.DataFrame) -> dict:
    assert_no_leakage(PRICE_NUMERIC_FEATURES + PRICE_CATEGORICAL_FEATURES)
    valid = df[
        pd.to_numeric(df["average_daily_rate"], errors="coerce").between(1, 1000)
    ].copy()
    train, calibration, validation, test = split_by_booking_date(valid)
    y_train = train["average_daily_rate"].astype(float)
    y_calibration = calibration["average_daily_rate"].astype(float).to_numpy()
    y_validation = validation["average_daily_rate"].astype(float).to_numpy()
    y_test = test["average_daily_rate"].astype(float).to_numpy()

    calibration_predictions: dict[float, np.ndarray] = {}
    validation_predictions: dict[float, np.ndarray] = {}
    test_predictions: dict[float, np.ndarray] = {}
    for q in (0.25, 0.50, 0.75):
        print(f"FIT price_quantile={q}")
        model = make_price_model(q)
        model.fit(train, y_train)
        calibration_predictions[q] = model.predict(calibration)
        validation_predictions[q] = model.predict(validation)
        test_predictions[q] = model.predict(test)

    raw_lower_calibration = np.minimum(
        calibration_predictions[0.25], calibration_predictions[0.75]
    )
    raw_upper_calibration = np.maximum(
        calibration_predictions[0.25], calibration_predictions[0.75]
    )
    nonconformity = np.maximum.reduce(
        [
            raw_lower_calibration - y_calibration,
            y_calibration - raw_upper_calibration,
            np.zeros(len(y_calibration)),
        ]
    )
    qhat = finite_sample_quantile(nonconformity, coverage=0.50)

    def interval_result(
        y: np.ndarray,
        preds: dict[float, np.ndarray],
    ) -> tuple[float, float, np.ndarray, np.ndarray]:
        raw_lower = np.minimum(preds[0.25], preds[0.75])
        raw_upper = np.maximum(preds[0.25], preds[0.75])
        lower = raw_lower - qhat
        upper = raw_upper + qhat
        raw_coverage = float(np.mean((y >= raw_lower) & (y <= raw_upper)))
        calibrated_coverage = float(np.mean((y >= lower) & (y <= upper)))
        return raw_coverage, calibrated_coverage, lower, upper

    raw_validation_coverage, validation_coverage, _, _ = interval_result(
        y_validation, validation_predictions
    )
    raw_test_coverage, test_coverage, test_lower, test_upper = interval_result(
        y_test, test_predictions
    )

    band = np.where(
        y_test < test_lower,
        "below_reference",
        np.where(y_test > test_upper, "above_reference", "within_reference_band"),
    )
    band_share = pd.Series(band).value_counts(normalize=True).to_dict()

    return {
        "target": "ADR quoted on real bookings; cancelled and non-cancelled bookings are both retained",
        "valid_booking_rows": int(len(valid)),
        "train_rows": int(len(train)),
        "calibration_rows": int(len(calibration)),
        "validation_rows": int(len(validation)),
        "test_rows": int(len(test)),
        "median_model_test": regression_metrics(y_test, test_predictions[0.50]),
        "raw_central_50pct_interval_coverage_validation": raw_validation_coverage,
        "calibrated_central_50pct_interval_coverage_validation": validation_coverage,
        "raw_central_50pct_interval_coverage_test": raw_test_coverage,
        "calibrated_central_50pct_interval_coverage_test": test_coverage,
        "conformal_expansion_adr_units": qhat,
        "observed_price_position_share_test": {
            k: float(v) for k, v in band_share.items()
        },
        "interpretation": "This is a comparable-booking ADR reference band with split-conformal interval calibration. It is not a causal price-elasticity estimate and it does not claim an optimal price.",
    }


def run_weekly_demand_forecast(df: pd.DataFrame) -> dict:
    completed = df[df["is_canceled"] == 0].copy()
    completed["room_nights"] = completed["total_nights"].clip(lower=0)
    completed["week"] = completed["arrival_date"].dt.to_period("W-SUN").dt.start_time
    weekly = completed.groupby("week", as_index=False).agg(
        room_nights=("room_nights", "sum"),
        completed_bookings=("is_canceled", "size"),
    )
    all_weeks = pd.date_range(weekly["week"].min(), weekly["week"].max(), freq="7D")
    weekly = (
        weekly.set_index("week")
        .reindex(all_weeks)
        .fillna(0)
        .rename_axis("week")
        .reset_index()
    )
    y = weekly["room_nights"].astype(float)
    for lag in (1, 2, 4, 13, 52):
        weekly[f"lag_{lag}"] = y.shift(lag)
    weekly["roll_4"] = y.shift(1).rolling(4).mean()
    weekly["roll_13"] = y.shift(1).rolling(13).mean()
    weekly["trend"] = np.arange(len(weekly))
    iso = weekly["week"].dt.isocalendar().week.astype(int)
    weekly["week_sin"] = np.sin(2 * np.pi * iso / 52.18)
    weekly["week_cos"] = np.cos(2 * np.pi * iso / 52.18)

    model_features = [
        "lag_1",
        "lag_2",
        "lag_4",
        "lag_13",
        "roll_4",
        "roll_13",
        "trend",
        "week_sin",
        "week_cos",
    ]
    eligible = weekly.dropna(subset=model_features).copy()
    train = eligible[eligible["week"] < pd.Timestamp("2016-10-01")]
    validation = eligible[
        (eligible["week"] >= pd.Timestamp("2016-10-01"))
        & (eligible["week"] < pd.Timestamp("2017-01-01"))
    ]
    test = eligible[eligible["week"] >= pd.Timestamp("2017-01-01")].dropna(
        subset=["lag_52"]
    )
    if min(len(train), len(validation), len(test)) < 8:
        raise ValueError(
            f"Insufficient weekly rows: train={len(train)}, validation={len(validation)}, test={len(test)}"
        )

    candidate_models = {
        "ridge": Pipeline(
            [("scale", StandardScaler()), ("model", Ridge(alpha=10.0))]
        ),
        "hist_gradient_boosting": HistGradientBoostingRegressor(
            learning_rate=0.05,
            max_iter=180,
            max_leaf_nodes=9,
            min_samples_leaf=8,
            l2_regularization=4.0,
            random_state=42,
        ),
    }
    validation_scores: dict[str, dict] = {}
    for name, model in candidate_models.items():
        model.fit(train[model_features], train["room_nights"])
        pred_validation = np.clip(model.predict(validation[model_features]), 0, None)
        validation_scores[name] = regression_metrics(
            validation["room_nights"], pred_validation
        )
    selected_name = min(
        validation_scores, key=lambda name: validation_scores[name]["wape"]
    )

    pre_test = eligible[eligible["week"] < pd.Timestamp("2017-01-01")]
    selected = candidate_models[selected_name]
    selected.fit(pre_test[model_features], pre_test["room_nights"])
    pred = np.clip(selected.predict(test[model_features]), 0, None)
    seasonal = np.clip(test["lag_52"].to_numpy(), 0, None)
    rolling = np.clip(test["roll_4"].to_numpy(), 0, None)

    metrics = {
        "seasonal_naive_lag52": regression_metrics(test["room_nights"], seasonal),
        "rolling_4_week": regression_metrics(test["room_nights"], rolling),
        "selected_model": regression_metrics(test["room_nights"], pred),
    }
    best_baseline_wape = min(
        metrics["seasonal_naive_lag52"]["wape"],
        metrics["rolling_4_week"]["wape"],
    )
    model_wape = metrics["selected_model"]["wape"]
    promote = bool(model_wape < best_baseline_wape * 0.98)
    return {
        "target": "one-week-ahead completed room-nights, evaluated with lagged observed outcomes only",
        "train_weeks": int(len(train)),
        "validation_weeks": int(len(validation)),
        "test_weeks": int(len(test)),
        "validation_candidate_metrics": validation_scores,
        "selected_model": selected_name,
        "metrics": metrics,
        "promotion_gate": {
            "rule": "select the candidate on a pre-test validation window, then promote only if future-test WAPE improves by at least 2% relative to the best simple baseline",
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
    calendar = calendar[
        calendar["date"].notna() & calendar["price_value"].between(1, 5000)
    ].copy()

    if {"id", "room_type"}.issubset(listings.columns):
        entire_home_ids = set(
            pd.to_numeric(
                listings.loc[listings["room_type"].eq("Entire home/apt"), "id"],
                errors="coerce",
            )
            .dropna()
            .astype(int)
        )
        calendar_ids = pd.to_numeric(calendar["listing_id"], errors="coerce")
        market = calendar[calendar_ids.isin(entire_home_ids)].copy()
        segment_name = "Entire home/apt"
    else:
        market = calendar.copy()
        segment_name = "all listings"

    snapshot_date = pd.Timestamp("2024-12-25")
    window = market[
        (market["date"] >= snapshot_date)
        & (market["date"] < snapshot_date + pd.Timedelta(days=180))
    ].copy()
    listing_level = window.groupby("listing_id").agg(
        asking_price=("price_value", "median"),
        availability_rate=("is_available", "mean"),
        calendar_days=("date", "size"),
    )
    listing_level = listing_level[listing_level["calendar_days"] >= 170].copy()

    window["week"] = window["date"].dt.to_period("W-SUN").dt.start_time
    weekly = (
        window.groupby("week")
        .agg(
            listing_days=("listing_id", "size"),
            distinct_listings=("listing_id", "nunique"),
            availability_rate=("is_available", "mean"),
        )
        .reset_index()
    )
    weekly["expected_listing_days"] = weekly["distinct_listings"] * 7
    complete_weekly = weekly[
        weekly["listing_days"] >= 0.99 * weekly["expected_listing_days"]
    ].copy()

    price_q = listing_level["asking_price"].quantile([0.25, 0.5, 0.75]).to_dict()
    listing_price_availability_corr = float(
        listing_level["asking_price"].corr(
            listing_level["availability_rate"], method="spearman"
        )
    )
    if len(complete_weekly) == 0:
        min_week = max_week = None
        min_availability = max_availability = float("nan")
    else:
        min_row = complete_weekly.loc[complete_weekly["availability_rate"].idxmin()]
        max_row = complete_weekly.loc[complete_weekly["availability_rate"].idxmax()]
        min_week = str(pd.Timestamp(min_row["week"]).date())
        max_week = str(pd.Timestamp(max_row["week"]).date())
        min_availability = float(min_row["availability_rate"])
        max_availability = float(max_row["availability_rate"])

    return {
        "snapshot": "Greater Manchester, 2024-12-25 Inside Airbnb public snapshot",
        "segment": segment_name,
        "listings_rows": int(len(listings)),
        "calendar_rows_loaded": int(len(calendar)),
        "analysis_window_days": 180,
        "analysis_listing_days": int(len(window)),
        "analysis_distinct_listings": int(window["listing_id"].nunique()),
        "listing_level_complete_rows": int(len(listing_level)),
        "asking_price_p25": float(price_q.get(0.25, float("nan"))),
        "asking_price_median": float(price_q.get(0.5, float("nan"))),
        "asking_price_p75": float(price_q.get(0.75, float("nan"))),
        "listing_price_vs_availability_spearman": listing_price_availability_corr,
        "complete_week_count": int(len(complete_weekly)),
        "lowest_complete_week_availability": min_availability,
        "lowest_complete_week_start": min_week,
        "highest_complete_week_availability": max_availability,
        "highest_complete_week_start": max_week,
        "availability_range_percentage_points": (
            (max_availability - min_availability) * 100
            if not np.isnan(min_availability) and not np.isnan(max_availability)
            else float("nan")
        ),
        "caveat": "The Airbnb calendar does not distinguish a booked date from a host-blocked unavailable date. Availability is therefore used only as a market-availability proxy. The snapshot also shows effectively static per-listing asking prices over this forward calendar, so no dynamic price-response claim is made.",
    }


def executive_summary(metrics: dict) -> str:
    cancellation = metrics["cancellation"]
    champion = cancellation["promotion_gate"]["champion"]
    champion_test = cancellation["test_metrics"][champion]
    demand = metrics["demand_forecast"]
    price = metrics["price_benchmark"]
    uk = metrics.get("uk_market")
    best_baseline_wape = min(
        demand["metrics"]["seasonal_naive_lag52"]["wape"],
        demand["metrics"]["rolling_4_week"]["wape"],
    )

    lines = [
        "# Executive summary",
        "",
        "This is a real-data accommodation analytics case study built around commercial questions that also appear in holiday-rental data science: demand forecasting, cancellation-aware revenue reliability, comparable-booking pricing and model monitoring.",
        "",
        f"The cancellation champion is **{champion}**, selected on a pre-test validation period. On the untouched future booking-time holdout it has ROC-AUC **{champion_test['roc_auc']:.3f}**, average precision **{champion_test['average_precision']:.3f}** and Brier score **{champion_test['brier']:.3f}**.",
        f"The top-risk 10% of future bookings has cancellation rate **{cancellation['top_10pct_risk']['top_cancel_rate']:.1%}** versus **{cancellation['top_10pct_risk']['overall_cancel_rate']:.1%}** overall. A separate ablation removes deposit type to check dependence on a policy-sensitive feature.",
        f"Monitoring **{'flags' if cancellation['drift']['retrain_review_flag'] else 'does not flag'}** the future period for model review: max PSI is **{cancellation['drift']['max_psi']:.3f}**, Brier changes by **{cancellation['drift']['brier_degradation']:+.3f}**, and cancellation-adjusted gross-value proxy error is **{cancellation['revenue_reliability']['relative_error']:+.1%}**.",
        f"The booking-ADR median reference model has test MAE **{price['median_model_test']['mae']:.2f}** ADR units. Split-conformal calibration gives central-50% interval coverage of **{price['calibrated_central_50pct_interval_coverage_validation']:.1%}** on validation and **{price['calibrated_central_50pct_interval_coverage_test']:.1%}** on the future test period.",
        f"The pre-test-selected weekly demand model has future-test WAPE **{demand['metrics']['selected_model']['wape']:.1%}** versus **{best_baseline_wape:.1%}** for the best simple baseline; it is **{'promoted' if demand['promotion_gate']['model_promoted'] else 'not promoted'}** under the pre-set gate.",
    ]
    if uk:
        lines.extend(
            [
                f"A one-time UK market read uses **{uk['analysis_listing_days']:,} listing-days** across **{uk['analysis_distinct_listings']:,} {uk['segment']} listings** in Greater Manchester. Median asking price is **£{uk['asking_price_median']:.0f}**, and complete-week availability varies by **{uk['availability_range_percentage_points']:.1f} percentage points** over the 180-day forward window.",
                "Inside Airbnb unavailable dates are not labelled as bookings, and its calendar prices in this snapshot are effectively static within listing; neither is used for a booking or dynamic-pricing claim.",
            ]
        )
    lines.extend(
        [
            "",
            "## Decision boundary",
            "",
            "The pricing component is a comparable-booking ADR reference band, not a causal price-elasticity model. No claim is made that changing a quoted price would cause the observed revenue response. Model selection, promotion and review use explicit pre-test and monitoring gates.",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", default="reports/generated")
    parser.add_argument(
        "--include-uk-market",
        action="store_true",
        help=(
            "Run the one-time Greater Manchester Inside Airbnb market read. "
            "It is off by default so CI does not repeatedly download the source files."
        ),
    )
    args = parser.parse_args()
    out = Path(args.output_dir)
    out.mkdir(parents=True, exist_ok=True)

    hotel = load_hotel_data()
    metrics: dict = {
        "data": {
            "hotel_rows": int(len(hotel)),
            "arrival_date_min": str(hotel["arrival_date"].min().date()),
            "arrival_date_max": str(hotel["arrival_date"].max().date()),
            "booking_date_min": str(hotel["booking_date"].min().date()),
            "booking_date_max": str(hotel["booking_date"].max().date()),
            "hotel_cancel_rate": float(hotel["is_canceled"].mean()),
        },
        "cancellation": run_cancellation_model(hotel),
        "price_benchmark": run_price_benchmark(hotel),
        "demand_forecast": run_weekly_demand_forecast(hotel),
    }

    if args.include_uk_market:
        try:
            metrics["uk_market"] = run_inside_airbnb_market()
            metrics["uk_market_status"] = "success"
        except Exception as exc:
            metrics["uk_market_status"] = f"failed: {type(exc).__name__}: {exc}"
            print(f"UK_MARKET_WARNING {metrics['uk_market_status']}", file=sys.stderr)
    else:
        metrics["uk_market_status"] = "skipped_by_default_to_avoid_repeated_source_downloads"

    write_json(out / "metrics.json", metrics)
    (out / "executive_summary.md").write_text(executive_summary(metrics))

    print("FORGE_METRICS_JSON_START")
    print(json.dumps(metrics, indent=2, sort_keys=True, default=str))
    print("FORGE_METRICS_JSON_END")
    print(executive_summary(metrics))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
