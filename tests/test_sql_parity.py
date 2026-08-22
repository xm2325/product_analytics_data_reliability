from pathlib import Path

import duckdb
import pandas as pd

from product_analytics.generator import generate_events
from product_analytics.metrics import daily_metrics
from product_analytics.quality import certify_events


ROOT = Path(__file__).resolve().parents[1]


def _controlled_fault_frame() -> pd.DataFrame:
    raw = generate_events(days=15, seed=29, inject_faults=False)
    purchase = raw.loc[raw["event_type"].eq("purchase")].iloc[[0]].copy()
    raw = pd.concat([raw, purchase], ignore_index=True)
    identity_idx = raw.index[raw["event_type"].eq("first_open")][5]
    raw.loc[identity_idx, "user_id"] = None
    return raw


def test_sql_silver_matches_python_certification():
    raw = _controlled_fault_frame()
    python_silver, report = certify_events(raw)

    con = duckdb.connect()
    try:
        con.register("bronze_df", raw)
        con.execute("CREATE TABLE bronze_events AS SELECT * FROM bronze_df")
        sql = (ROOT / "sql" / "silver_events.sql").read_text(encoding="utf-8")
        sql_silver = con.execute(sql).df()
    finally:
        con.close()

    assert report.rows_rejected == 2
    assert len(sql_silver) == len(python_silver)
    assert set(sql_silver["event_id"]) == set(python_silver["event_id"])


def test_sql_gold_matches_python_gold():
    raw = _controlled_fault_frame()
    python_silver, _ = certify_events(raw)
    python_gold = daily_metrics(python_silver).copy()

    con = duckdb.connect()
    try:
        con.register("bronze_df", raw)
        con.execute("CREATE TABLE bronze_events AS SELECT * FROM bronze_df")
        silver_sql = (ROOT / "sql" / "silver_events.sql").read_text(encoding="utf-8")
        con.execute(f"CREATE TABLE silver_events AS {silver_sql}")
        gold_sql = (ROOT / "sql" / "gold_daily_metrics.sql").read_text(encoding="utf-8")
        sql_gold = con.execute(gold_sql).df()
    finally:
        con.close()

    columns = [
        "product",
        "date",
        "dau",
        "dau_legacy_any_event",
        "dau_definition_delta",
        "dau_definition_delta_pct",
        "first_open",
        "trial_start",
        "paid_subscription",
        "revenue_gbp",
        "conversion_first_open",
        "conversion_trial_start",
    ]
    python_gold = python_gold[columns].copy()
    sql_gold = sql_gold[columns].copy()
    python_gold["date"] = python_gold["date"].astype(str)
    sql_gold["date"] = sql_gold["date"].astype(str)
    python_gold = python_gold.sort_values(["product", "date"]).reset_index(drop=True)
    sql_gold = sql_gold.sort_values(["product", "date"]).reset_index(drop=True)

    pd.testing.assert_frame_equal(
        python_gold,
        sql_gold,
        check_dtype=False,
        check_exact=False,
        rtol=1e-12,
        atol=1e-12,
    )
