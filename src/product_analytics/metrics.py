from __future__ import annotations

from dataclasses import asdict, dataclass

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
    df = events.copy()
    df["date"] = pd.to_datetime(df["event_ts"], utc=True).dt.date

    dau = df.groupby(["product", "date"])["user_id"].nunique().rename("dau")
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
    out = pd.concat([dau, counts, revenue], axis=1).fillna(0).reset_index()
    for col in ["first_open", "trial_start", "paid_subscription"]:
        if col not in out:
            out[col] = 0
    out["conversion_first_open"] = out["paid_subscription"] / out["first_open"].replace(0, pd.NA)
    out["conversion_trial_start"] = out["paid_subscription"] / out["trial_start"].replace(0, pd.NA)
    return out.sort_values(["product", "date"]).reset_index(drop=True)


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
