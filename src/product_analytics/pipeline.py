from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

import duckdb
import pandas as pd

from .metrics import daily_metrics
from .quality import certify_events_with_rejects, reconcile_revenue


def run_pipeline(events: pd.DataFrame, database_path: str | Path = ":memory:") -> dict[str, object]:
    """Run Bronze → Silver → Gold while preserving rejection evidence."""
    certified, quality, rejected = certify_events_with_rejects(events)
    gold = daily_metrics(certified)
    reconciliation = reconcile_revenue(events, certified)
    quality_frame = pd.DataFrame([asdict(quality)])

    con = duckdb.connect(str(database_path))
    try:
        for name, frame in {
            "bronze_df": events,
            "silver_df": certified,
            "rejected_df": rejected,
            "gold_df": gold,
            "reconciliation_df": reconciliation,
            "quality_df": quality_frame,
        }.items():
            con.register(name, frame)

        con.execute("CREATE OR REPLACE TABLE bronze_events AS SELECT * FROM bronze_df")
        con.execute("CREATE OR REPLACE TABLE silver_events AS SELECT * FROM silver_df")
        con.execute("CREATE OR REPLACE TABLE rejected_events AS SELECT * FROM rejected_df")
        con.execute("CREATE OR REPLACE TABLE gold_daily_metrics AS SELECT * FROM gold_df")
        con.execute("CREATE OR REPLACE TABLE revenue_reconciliation AS SELECT * FROM reconciliation_df")
        con.execute("CREATE OR REPLACE TABLE quality_report AS SELECT * FROM quality_df")
    finally:
        con.close()

    return {
        "quality_report": quality,
        "rejected_events": rejected,
        "silver_events": certified,
        "gold_daily_metrics": gold,
        "revenue_reconciliation": reconciliation,
    }
