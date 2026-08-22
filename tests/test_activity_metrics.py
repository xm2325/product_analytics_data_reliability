from dataclasses import replace

import pandas as pd

from product_analytics.config import ProductConfig
from product_analytics.generator import generate_events
from product_analytics.metrics import (
    activity_retention,
    daily_metrics,
    dau_definition_migration,
    retention_contract_records,
    retention_maturity_ledger,
    retention_maturity_summary,
    retention_summary,
)


def _event(event_id, user_id, event_type, ts, revenue=0.0):
    return {
        "event_id": event_id,
        "user_id": user_id,
        "product": "notes_app",
        "event_type": event_type,
        "event_ts": pd.Timestamp(ts, tz="UTC"),
        "platform": "ios",
        "source": "organic",
        "revenue_gbp": revenue,
    }


def test_dau_v2_requires_app_open_while_legacy_counts_any_event():
    events = pd.DataFrame(
        [
            _event("e1", "u1", "first_open", "2026-01-01 08:00"),
            _event("e2", "u1", "app_open", "2026-01-01 08:01"),
            _event("e3", "u2", "first_open", "2026-01-01 09:00"),
            _event("e4", "u2", "app_open", "2026-01-01 09:01"),
            _event("e5", "u1", "purchase", "2026-01-02 10:00", 7.99),
        ]
    )
    gold = daily_metrics(events)
    day2 = gold.loc[gold["date"].eq(pd.Timestamp("2026-01-02").date())].iloc[0]
    assert day2["dau"] == 0
    assert day2["dau_legacy_any_event"] == 1
    assert day2["dau_definition_delta"] == 1

    migration = dau_definition_migration(gold)
    assert (migration["dau_legacy_any_event"] >= migration["dau"]).all()
    assert (migration["delta_users"] > 0).any()


def test_activity_retention_uses_exact_return_horizons():
    events = pd.DataFrame(
        [
            _event("e1", "u1", "first_open", "2026-01-01 08:00"),
            _event("e2", "u1", "app_open", "2026-01-01 08:01"),
            _event("e3", "u1", "app_open", "2026-01-08 08:00"),
            _event("e4", "u1", "app_open", "2026-01-31 08:00"),
            _event("e5", "u2", "first_open", "2026-01-01 09:00"),
            _event("e6", "u2", "app_open", "2026-01-01 09:01"),
            _event("e7", "u2", "app_open", "2026-01-08 09:00"),
        ]
    )
    cohorts = activity_retention(
        events,
        horizons=(7, 30),
        observation_end_by_product={"notes_app": "2026-01-31"},
    )
    summary = retention_summary(cohorts).set_index("horizon_days")
    assert summary.loc[7, "eligible_users"] == 2
    assert summary.loc[7, "retention_rate"] == 1.0
    assert summary.loc[30, "eligible_users"] == 2
    assert summary.loc[30, "retention_rate"] == 0.5


def test_immature_cohort_is_visible_but_future_return_is_not_used():
    events = pd.DataFrame(
        [
            _event("e1", "u_old", "first_open", "2026-01-01 08:00"),
            _event("e2", "u_old", "app_open", "2026-01-08 08:00"),
            _event("e3", "u_new", "first_open", "2026-01-25 08:00"),
            # This return exists in the source, but it is after analysis_as_of.
            _event("e4", "u_new", "app_open", "2026-02-01 08:00"),
        ]
    )
    ledger = retention_maturity_ledger(
        events,
        horizons=(7,),
        observation_end_by_product={"notes_app": "2026-01-31"},
    )
    old = ledger.loc[ledger["cohort_date"].eq(pd.Timestamp("2026-01-01").date())].iloc[0]
    new = ledger.loc[ledger["cohort_date"].eq(pd.Timestamp("2026-01-25").date())].iloc[0]

    assert bool(old["mature"])
    assert old["eligible_users"] == 1
    assert old["retained_users"] == 1
    assert not bool(new["mature"])
    assert new["eligible_users"] == 0
    assert new["excluded_users"] == 1
    assert pd.isna(new["retained_users"])
    assert pd.isna(new["retention_rate"])
    assert new["exclusion_reason"] == "target_date_after_analysis_as_of"

    cohorts = activity_retention(
        events,
        horizons=(7,),
        observation_end_by_product={"notes_app": "2026-01-31"},
    )
    assert len(cohorts) == 1
    assert cohorts.iloc[0]["eligible_users"] == 1


def test_longer_retention_horizon_has_less_mature_evidence():
    raw = generate_events(days=60, seed=37, inject_faults=False)
    first_open = raw.loc[raw["event_type"].eq("first_open")].copy()
    as_of = {
        product: pd.to_datetime(frame["event_ts"], utc=True).dt.date.max()
        for product, frame in first_open.groupby("product")
    }
    ledger = retention_maturity_ledger(raw, horizons=(7, 30), observation_end_by_product=as_of)
    summary = retention_maturity_summary(ledger).pivot(
        index="product", columns="horizon_days", values="eligible_user_fraction"
    )
    assert (summary[30] < summary[7]).all()


def test_retention_contracts_make_maturity_denominator_explicit():
    contracts = {row["name"]: row for row in retention_contract_records()}
    assert set(contracts) == {"d7_activity_retention", "d30_activity_retention"}
    assert contracts["d7_activity_retention"]["horizon_days"] == 7
    assert contracts["d30_activity_retention"]["horizon_days"] == 30
    assert all(row["return_window"] == "exact_calendar_day" for row in contracts.values())
    assert all("analysis_as_of" in row["denominator"] for row in contracts.values())


def test_activity_rng_does_not_change_commercial_funnel_stream():
    base = ProductConfig("test_product", 15.0, 0.4, 0.5, 9.99, activity_horizon_days=0)
    active = replace(base, activity_horizon_days=30)

    no_return_activity = generate_events(days=20, seed=101, products=(base,), inject_faults=False)
    with_return_activity = generate_events(days=20, seed=101, products=(active,), inject_faults=False)

    commercial_types = {"first_open", "trial_start", "paid_subscription", "purchase"}
    columns = ["user_id", "product", "event_type", "event_ts", "platform", "source", "revenue_gbp"]
    left = (
        no_return_activity.loc[no_return_activity["event_type"].isin(commercial_types), columns]
        .sort_values(columns[:-1])
        .reset_index(drop=True)
    )
    right = (
        with_return_activity.loc[with_return_activity["event_type"].isin(commercial_types), columns]
        .sort_values(columns[:-1])
        .reset_index(drop=True)
    )
    pd.testing.assert_frame_equal(left, right)
