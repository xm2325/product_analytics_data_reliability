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


@dataclass(frozen=True)
class RetentionContract:
    name: str
    cohort_event: str
    return_event: str
    horizon_days: int
    return_window: str
    denominator: str
    grain: str = "product-cohort_date"
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


RETENTION_CONTRACTS = {
    "d7_activity_retention": RetentionContract(
        "d7_activity_retention",
        cohort_event="first_open",
        return_event="app_open",
        horizon_days=7,
        return_window="exact_calendar_day",
        denominator="users in acquisition cohorts whose D7 target date is on or before analysis_as_of",
    ),
    "d30_activity_retention": RetentionContract(
        "d30_activity_retention",
        cohort_event="first_open",
        return_event="app_open",
        horizon_days=30,
        return_window="exact_calendar_day",
        denominator="users in acquisition cohorts whose D30 target date is on or before analysis_as_of",
    ),
}


def metric_contract_records() -> list[dict[str, str]]:
    """Return deterministic, machine-readable metric definitions."""
    return [asdict(METRIC_CONTRACTS[name]) for name in sorted(METRIC_CONTRACTS)]


def retention_contract_records() -> list[dict[str, object]]:
    """Return deterministic contracts for exact-day activity retention."""
    return [asdict(RETENTION_CONTRACTS[name]) for name in sorted(RETENTION_CONTRACTS)]


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


def retention_maturity_ledger(
    events: pd.DataFrame,
    horizons: tuple[int, ...] = (7, 30),
    observation_end_by_product: dict[str, object] | None = None,
) -> pd.DataFrame:
    """Audit every cohort/horizon before it is allowed into retention.

    The ledger keeps immature cohorts visible rather than silently dropping
    them. Future app-open events may exist in a simulation or backfilled source,
    but they are not allowed to leak into a metric whose declared
    ``analysis_as_of`` is earlier than the target date.
    """
    if not horizons or any(horizon <= 0 for horizon in horizons):
        raise ValueError("Retention horizons must be positive")

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
    activity["returned"] = 1

    rows: list[dict[str, object]] = []
    for product, product_acquisitions in acquisitions.groupby("product"):
        if observation_end_by_product and product in observation_end_by_product:
            analysis_as_of = pd.Timestamp(observation_end_by_product[product]).date()
        else:
            analysis_as_of = df.loc[df["product"].eq(product), "date"].max()

        for horizon in sorted(set(horizons)):
            user_targets = product_acquisitions.copy()
            user_targets["target_date"] = user_targets["cohort_date"].map(
                lambda value: value + timedelta(days=horizon)
            )
            joined = user_targets.merge(
                activity,
                on=["product", "user_id", "target_date"],
                how="left",
            )
            joined["returned"] = joined["returned"].fillna(0).astype(int)
            joined["mature"] = joined["target_date"].le(analysis_as_of)

            cohort = (
                joined.groupby(["cohort_date", "target_date", "mature"], as_index=False)
                .agg(cohort_users=("user_id", "size"), observed_returns=("returned", "sum"))
            )
            for record in cohort.to_dict(orient="records"):
                mature = bool(record["mature"])
                cohort_users = int(record["cohort_users"])
                retained_users = int(record["observed_returns"]) if mature else pd.NA
                rows.append(
                    {
                        "product": product,
                        "cohort_date": record["cohort_date"],
                        "horizon_days": int(horizon),
                        "target_date": record["target_date"],
                        "analysis_as_of": analysis_as_of,
                        "mature": mature,
                        "maturity_status": "mature" if mature else "immature",
                        "cohort_users": cohort_users,
                        "eligible_users": cohort_users if mature else 0,
                        "excluded_users": 0 if mature else cohort_users,
                        "retained_users": retained_users,
                        "retention_rate": (
                            float(retained_users) / cohort_users if mature and cohort_users else float("nan")
                        ),
                        "exclusion_reason": "" if mature else "target_date_after_analysis_as_of",
                    }
                )

    if not rows:
        return pd.DataFrame(
            columns=[
                "product",
                "cohort_date",
                "horizon_days",
                "target_date",
                "analysis_as_of",
                "mature",
                "maturity_status",
                "cohort_users",
                "eligible_users",
                "excluded_users",
                "retained_users",
                "retention_rate",
                "exclusion_reason",
            ]
        )
    return pd.DataFrame(rows).sort_values(["product", "horizon_days", "cohort_date"]).reset_index(drop=True)


def activity_retention(
    events: pd.DataFrame,
    horizons: tuple[int, ...] = (7, 30),
    observation_end_by_product: dict[str, object] | None = None,
) -> pd.DataFrame:
    """Calculate exact-day return rates from mature acquisition cohorts only."""
    ledger = retention_maturity_ledger(
        events,
        horizons=horizons,
        observation_end_by_product=observation_end_by_product,
    )
    mature = ledger.loc[ledger["mature"]].copy()
    if mature.empty:
        return pd.DataFrame(
            columns=["product", "cohort_date", "horizon_days", "eligible_users", "retained_users", "retention_rate"]
        )
    mature["retained_users"] = mature["retained_users"].astype(int)
    return mature[
        ["product", "cohort_date", "horizon_days", "eligible_users", "retained_users", "retention_rate"]
    ].reset_index(drop=True)


def retention_summary(cohort_retention: pd.DataFrame) -> pd.DataFrame:
    """Aggregate mature cohort retention using eligible-user weighting."""
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


def retention_maturity_summary(ledger: pd.DataFrame) -> pd.DataFrame:
    """Summarise how much cohort evidence is mature versus excluded."""
    if ledger.empty:
        return pd.DataFrame(
            columns=[
                "product",
                "horizon_days",
                "analysis_as_of",
                "cohorts",
                "mature_cohorts",
                "immature_cohorts",
                "cohort_users",
                "eligible_users",
                "excluded_users",
                "eligible_user_fraction",
            ]
        )
    working = ledger.copy()
    working["mature_int"] = working["mature"].astype(int)
    out = (
        working.groupby(["product", "horizon_days", "analysis_as_of"], as_index=False)
        .agg(
            cohorts=("cohort_date", "size"),
            mature_cohorts=("mature_int", "sum"),
            cohort_users=("cohort_users", "sum"),
            eligible_users=("eligible_users", "sum"),
            excluded_users=("excluded_users", "sum"),
        )
    )
    out["immature_cohorts"] = out["cohorts"] - out["mature_cohorts"]
    out["eligible_user_fraction"] = out["eligible_users"] / out["cohort_users"].replace(0, pd.NA)
    columns = [
        "product",
        "horizon_days",
        "analysis_as_of",
        "cohorts",
        "mature_cohorts",
        "immature_cohorts",
        "cohort_users",
        "eligible_users",
        "excluded_users",
        "eligible_user_fraction",
    ]
    return out[columns].sort_values(["product", "horizon_days"]).reset_index(drop=True)


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
