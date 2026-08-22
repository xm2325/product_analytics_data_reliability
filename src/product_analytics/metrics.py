from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import timedelta

import pandas as pd


@dataclass(frozen=True)
class MetricContract:
    name: str
    numerator: str
    denominator: str
    grain: str
    unit: str = "ratio"
    version: str = "1.0"


METRIC_CONTRACTS = {
    "daily_active_users": MetricContract(
        "daily_active_users",
        "unique users with app_open",
        "not applicable",
        "product-date",
        unit="users",
        version="2.0",
    ),
    "daily_active_users_legacy_any_event": MetricContract(
        "daily_active_users_legacy_any_event",
        "unique users with any certified event",
        "not applicable",
        "product-date",
        unit="users",
        version="1.0-deprecated",
    ),
    "paid_conversion_from_first_open": MetricContract(
        "paid_conversion_from_first_open",
        "users with paid_subscription",
        "users with first_open",
        "product",
    ),
    "paid_conversion_from_trial_start": MetricContract(
        "paid_conversion_from_trial_start",
        "users with paid_subscription",
        "users with trial_start",
        "product",
    ),
}


def metric_contract_records() -> list[dict[str, str]]:
    """Return deterministic, machine-readable metric definitions."""
    return [asdict(METRIC_CONTRACTS[name]) for name in sorted(METRIC_CONTRACTS)]


def daily_metrics(events: pd.DataFrame) -> pd.DataFrame:
    """Calculate Gold metrics with DAU v2 and the deprecated v1 dual-run."""
    df = events.copy()
    df["date"] = pd.to_datetime(df["event_ts"], utc=True).dt.date

    dau_legacy = (
        df.groupby(["product", "date"])["user_id"]
        .nunique()
        .rename("dau_legacy_any_event")
    )
    dau = (
        df.loc[df["event_type"].eq("app_open")]
        .groupby(["product", "date"])["user_id"]
        .nunique()
        .rename("dau")
    )
    counts = (
        df[df["event_type"].isin(["first_open", "trial_start", "paid_subscription"])]
        .groupby(["product", "date", "event_type"])["user_id"]
        .nunique()
        .unstack("event_type", fill_value=0)
    )
    revenue = (
        df.loc[df["event_type"].eq("purchase")]
        .groupby(["product", "date"])["revenue_gbp"]
        .sum()
        .rename("revenue_gbp")
    )
    out = pd.concat([dau, dau_legacy, counts, revenue], axis=1).fillna(0).reset_index()
    for col in ["first_open", "trial_start", "paid_subscription"]:
        if col not in out:
            out[col] = 0

    out["dau"] = out["dau"].astype(int)
    out["dau_legacy_any_event"] = out["dau_legacy_any_event"].astype(int)
    out["dau_definition_delta"] = out["dau_legacy_any_event"] - out["dau"]
    out["dau_definition_delta_pct"] = (
        out["dau_definition_delta"] / out["dau"].replace(0, pd.NA)
    )
    out["conversion_first_open"] = out["paid_subscription"] / out["first_open"].replace(0, pd.NA)
    out["conversion_trial_start"] = out["paid_subscription"] / out["trial_start"].replace(0, pd.NA)
    return out.sort_values(["product", "date"]).reset_index(drop=True)


def dau_definition_migration(gold_metrics: pd.DataFrame) -> pd.DataFrame:
    """Return the daily v1/v2 DAU dual-run used to govern metric migration."""
    required = {"product", "date", "dau", "dau_legacy_any_event"}
    missing = required.difference(gold_metrics.columns)
    if missing:
        raise ValueError(f"Missing Gold columns: {sorted(missing)}")
    out = gold_metrics[["product", "date", "dau", "dau_legacy_any_event"]].copy()
    out["delta_users"] = out["dau_legacy_any_event"] - out["dau"]
    out["delta_pct_of_v2"] = out["delta_users"] / out["dau"].replace(0, pd.NA)
    return out.sort_values(["product", "date"]).reset_index(drop=True)


def activity_retention(
    events: pd.DataFrame,
    horizons: tuple[int, ...] = (7, 30),
    observation_end_by_product: dict[str, object] | None = None,
) -> pd.DataFrame:
    """Calculate acquisition-cohort return rates from explicit app-open events.

    A user is retained at horizon h when they have an `app_open` exactly h
    calendar days after their first-open cohort date. Cohorts are included only
    when the supplied observation boundary makes that horizon fully mature.
    """
    df = events.copy()
    df["date"] = pd.to_datetime(df["event_ts"], utc=True).dt.date
    acquisitions = (
        df.loc[df["event_type"].eq("first_open")]
        .groupby(["product", "user_id"], as_index=False)["date"]
        .min()
        .rename(columns={"date": "cohort_date"})
    )
    activity = (
        df.loc[df["event_type"].eq("app_open"), ["product", "user_id", "date"]]
        .drop_duplicates()
        .rename(columns={"date": "target_date"})
    )
    activity["retained"] = 1

    rows: list[dict[str, object]] = []
    for product, product_acquisitions in acquisitions.groupby("product"):
        if observation_end_by_product and product in observation_end_by_product:
            observation_end = pd.Timestamp(observation_end_by_product[product]).date()
        else:
            product_dates = df.loc[df["product"].eq(product), "date"]
            observation_end = product_dates.max()

        for horizon in horizons:
            if horizon <= 0:
                raise ValueError("Retention horizons must be positive")
            mature = product_acquisitions.loc[
                product_acquisitions["cohort_date"].map(
                    lambda value: value + timedelta(days=horizon) <= observation_end
                )
            ].copy()
            if mature.empty:
                continue
            mature["target_date"] = mature["cohort_date"].map(
                lambda value: value + timedelta(days=horizon)
            )
            joined = mature.merge(
                activity,
                on=["product", "user_id", "target_date"],
                how="left",
            )
            joined["retained"] = joined["retained"].fillna(0).astype(int)
            cohort = joined.groupby("cohort_date")["retained"].agg(["size", "sum"]).reset_index()
            for record in cohort.to_dict(orient="records"):
                eligible = int(record["size"])
                retained = int(record["sum"])
                rows.append(
                    {
                        "product": product,
                        "cohort_date": record["cohort_date"],
                        "horizon_days": int(horizon),
                        "eligible_users": eligible,
                        "retained_users": retained,
                        "retention_rate": retained / eligible if eligible else float("nan"),
                    }
                )

    return pd.DataFrame(rows).sort_values(["product", "horizon_days", "cohort_date"]).reset_index(drop=True)


def retention_summary(cohort_retention: pd.DataFrame) -> pd.DataFrame:
    """Aggregate cohort retention using eligible-user weighting."""
    if cohort_retention.empty:
        return pd.DataFrame(
            columns=["product", "horizon_days", "eligible_users", "retained_users", "retention_rate"]
        )
    out = (
        cohort_retention.groupby(["product", "horizon_days"], as_index=False)
        .agg(eligible_users=("eligible_users", "sum"), retained_users=("retained_users", "sum"))
    )
    out["retention_rate"] = out["retained_users"] / out["eligible_users"]
    return out.sort_values(["product", "horizon_days"]).reset_index(drop=True)


def portfolio_conversion(events: pd.DataFrame) -> dict[str, float]:
    def users(event: str) -> int:
        return int(events.loc[events["event_type"].eq(event), "user_id"].nunique())

    paid = users("paid_subscription")
    opened = users("first_open")
    trial = users("trial_start")
    return {
        "paid_conversion_from_first_open": paid / opened if opened else float("nan"),
        "paid_conversion_from_trial_start": paid / trial if trial else float("nan"),
    }
