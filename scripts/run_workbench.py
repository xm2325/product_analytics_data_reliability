from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from product_analytics.forecasting import evaluate_forecast, seasonal_naive
from product_analytics.generator import generate_events
from product_analytics.metrics import portfolio_conversion
from product_analytics.pipeline import run_pipeline


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", default="build/reference")
    parser.add_argument("--days", type=int, default=120)
    parser.add_argument("--seed", type=int, default=2206)
    args = parser.parse_args()

    out = Path(args.output_dir)
    out.mkdir(parents=True, exist_ok=True)

    raw = generate_events(days=args.days, seed=args.seed, inject_faults=True)
    result = run_pipeline(raw, database_path=out / "workbench.duckdb")
    silver = result["silver_events"]
    gold = result["gold_daily_metrics"]
    reconciliation = result["revenue_reconciliation"]

    raw.to_csv(out / "bronze_events.csv", index=False)
    silver.to_csv(out / "silver_events.csv", index=False)
    gold.to_csv(out / "gold_daily_metrics.csv", index=False)
    reconciliation.to_csv(out / "revenue_reconciliation.csv", index=False)

    forecast_rows = []
    for product, frame in gold.groupby("product"):
        frame = frame.sort_values("date")
        for metric in ["dau", "revenue_gbp", "paid_subscription"]:
            backtest = seasonal_naive(frame[metric], season=7, holdout=28)
            evaluation = evaluate_forecast(f"{product}:{metric}", backtest)
            forecast_rows.append(asdict(evaluation))

    quality = asdict(result["quality_report"])
    summary = {
        "seed": args.seed,
        "days": args.days,
        "quality": quality,
        "portfolio_conversion": portfolio_conversion(silver),
        "forecast_evaluations": forecast_rows,
    }
    (out / "reference_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
