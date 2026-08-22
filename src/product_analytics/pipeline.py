from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd

from .metrics import daily_metrics
from .quality import QualityReport, certify_events, reconcile_revenue


def run_pipeline(events: pd.DataFrame, database_path: str | Path = ":memory:") -> dict[str, object]:
    """Run a compact Bronze → Silver → Gold pipeline and persist DuckDB tables."""
    certified, quality = certify_events(events)
    gold = daily_metrics(certified)
    reconciliation = reconcile_revenue(events, certified)

    con = duckdb.connect(str(database_path))
    try:
        con.register("bronze_df", events)
        con.register("silver_df", certified)
        con.register("gold_df", gold)
        con.execute("CREATE OR REPLACE TABLE bronze_events AS SELECT * FROM bronze_df")
        con.execute("CREATE OR REPLACE TABLE silver_events AS SELECT * FROM silver_df")
        con.execute("CREATE OR REPLACE TABLE gold_daily_metrics AS SELECT * FROM gold_df")
    finally:
        con.close()

    return {
        "quality_report": quality,
        "silver_events": certified,
        "gold_daily_metrics": gold,
        "revenue_reconciliation": reconciliation,
    }
