from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

import pandas as pd

from product_analytics.config import PRODUCTS
from product_analytics.contracts import event_contract
from product_analytics.forecasting import evaluate_forecast, mature_metric_history, seasonal_naive
from product_analytics.generator import generate_events
from product_analytics.metrics import metric_contract_records, portfolio_conversion
from product_analytics.pipeline import run_pipeline
from product_analytics.provenance import write_manifest


VERSION = "0.23.0"


def _write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the synthetic analytics reference run")
    parser.add_argument("--output-dir", default="build/reference")
    parser.add_argument("--days", type=int, default=120)
    parser.add_argument("--seed", type=int, default=2206)
    args = parser.parse_args()
    if args.days < 40:
        raise SystemExit("--days must be at least 40 so the 28-day forecast holdout is estimable")

    out = Path(args.output_dir)
    out.mkdir(parents=True, exist_ok=True)

    raw = generate_events(days=args.days, seed=args.seed, inject_faults=True)
    result = run_pipeline(raw, database_path=out / "workbench.duckdb")
    rejected = result["rejected_events"]
    silver = result["silver_events"]
    gold = result["gold_daily_metrics"]
    reconciliation = result["revenue_reconciliation"]

    outputs: list[Path] = []
    for name, frame in {
        "bronze_events.csv": raw,
        "rejected_events.csv": rejected,
        "silver_events.csv": silver,
        "gold_daily_metrics.csv": gold,
        "revenue_reconciliation.csv": reconciliation,
    }.items():
        path = out / name
        frame.to_csv(path, index=False)
        outputs.append(path)

    forecast_rows = []
    forecast_cutoffs: dict[str, str] = {}
    for product in sorted(gold["product"].unique()):
        frame, cutoff = mature_metric_history(gold, silver, product)
        forecast_cutoffs[product] = str(cutoff)
        for metric in ["dau", "revenue_gbp", "paid_subscription"]:
            backtest = seasonal_naive(frame[metric], season=7, holdout=28)
            evaluation = evaluate_forecast(f"{product}:{metric}", backtest)
            row = asdict(evaluation)
            row["observation_cutoff"] = str(cutoff)
            forecast_rows.append(row)
    forecast_frame = pd.DataFrame(forecast_rows).sort_values("metric").reset_index(drop=True)
    forecast_path = out / "forecast_evaluations.csv"
    forecast_frame.to_csv(forecast_path, index=False)
    outputs.append(forecast_path)

    quality = asdict(result["quality_report"])
    quality_path = out / "quality_report.json"
    _write_json(quality_path, quality)
    outputs.append(quality_path)

    metric_contracts_path = out / "metric_contracts.json"
    _write_json(metric_contracts_path, metric_contract_records())
    outputs.append(metric_contracts_path)

    event_contract_path = out / "event_contract.json"
    _write_json(event_contract_path, event_contract())
    outputs.append(event_contract_path)

    summary = {
        "version": VERSION,
        "seed": args.seed,
        "days": args.days,
        "products": [product.name for product in PRODUCTS],
        "quality": quality,
        "portfolio_conversion": portfolio_conversion(silver),
        "forecast_evaluations": forecast_rows,
        "forecast_observation_cutoff": forecast_cutoffs,
        "forecast_gate": {
            "approved": int(forecast_frame["approved"].sum()),
            "withheld": int((~forecast_frame["approved"]).sum()),
        },
        "revenue_reconciliation": reconciliation.to_dict(orient="records"),
    }
    summary_path = out / "reference_summary.json"
    _write_json(summary_path, summary)
    outputs.append(summary_path)

    # The database is an operational convenience. The manifest focuses on
    # portable tabular/JSON evidence so it can be compared across platforms.
    manifest = write_manifest(outputs, root=out, output=out / "MANIFEST.json")
    print(json.dumps({**summary, "manifest_artifacts": manifest["artifact_count"]}, indent=2))


if __name__ == "__main__":
    main()
