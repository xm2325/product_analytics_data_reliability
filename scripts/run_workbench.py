from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

import pandas as pd

from product_analytics.config import PRODUCTS
from product_analytics.contracts import event_contract
from product_analytics.forecasting import evaluate_forecast, mature_metric_history, seasonal_naive
from product_analytics.generator import generate_events, product_config_frame
from product_analytics.metrics import (
    activity_retention,
    dau_definition_migration,
    metric_contract_records,
    portfolio_conversion,
    retention_contract_records,
    retention_maturity_ledger,
    retention_maturity_summary,
    retention_summary,
)
from product_analytics.pipeline import run_pipeline
from product_analytics.provenance import write_manifest


VERSION = "0.25.0"


def _write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _migration_summary(migration: pd.DataFrame) -> pd.DataFrame:
    out = (
        migration.groupby("product", as_index=False)
        .agg(
            days=("date", "size"),
            mean_dau_v2=("dau", "mean"),
            mean_dau_v1=("dau_legacy_any_event", "mean"),
            mean_delta_users=("delta_users", "mean"),
            p95_delta_users=("delta_users", lambda values: float(values.quantile(0.95))),
        )
    )
    out["mean_delta_pct_of_v2"] = (
        out["mean_dau_v1"] - out["mean_dau_v2"]
    ) / out["mean_dau_v2"].replace(0, pd.NA)
    return out.sort_values("product").reset_index(drop=True)


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
        "product_config.csv": product_config_frame(),
    }.items():
        path = out / name
        frame.to_csv(path, index=False)
        outputs.append(path)

    # The last first_open date is the common reporting boundary. It prevents
    # simulator-generated follow-up after that date from leaking into either
    # forecast validation or retention cohorts that have not matured yet.
    forecast_rows = []
    analysis_as_of_by_product: dict[str, object] = {}
    mature_gold_parts: list[pd.DataFrame] = []
    for product in sorted(gold["product"].unique()):
        frame, cutoff = mature_metric_history(gold, silver, product)
        analysis_as_of_by_product[product] = cutoff
        mature_gold_parts.append(frame)
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

    mature_gold = pd.concat(mature_gold_parts, ignore_index=True)
    migration = dau_definition_migration(mature_gold)
    migration_summary = _migration_summary(migration)
    migration_path = out / "dau_definition_migration.csv"
    migration.to_csv(migration_path, index=False)
    outputs.append(migration_path)
    migration_summary_path = out / "dau_definition_migration_summary.csv"
    migration_summary.to_csv(migration_summary_path, index=False)
    outputs.append(migration_summary_path)

    maturity_ledger = retention_maturity_ledger(
        silver,
        horizons=(7, 30),
        observation_end_by_product=analysis_as_of_by_product,
    )
    maturity_summary = retention_maturity_summary(maturity_ledger)
    retention = activity_retention(
        silver,
        horizons=(7, 30),
        observation_end_by_product=analysis_as_of_by_product,
    )
    retention_overall = retention_summary(retention)

    for name, frame in {
        "retention_maturity_ledger.csv": maturity_ledger,
        "retention_maturity_summary.csv": maturity_summary,
        "activity_retention_cohorts.csv": retention,
        "activity_retention_summary.csv": retention_overall,
    }.items():
        path = out / name
        frame.to_csv(path, index=False)
        outputs.append(path)

    quality = asdict(result["quality_report"])
    quality_path = out / "quality_report.json"
    _write_json(quality_path, quality)
    outputs.append(quality_path)

    metric_contracts_path = out / "metric_contracts.json"
    _write_json(metric_contracts_path, metric_contract_records())
    outputs.append(metric_contracts_path)

    retention_contracts_path = out / "retention_contracts.json"
    _write_json(retention_contracts_path, retention_contract_records())
    outputs.append(retention_contracts_path)

    event_contract_path = out / "event_contract.json"
    _write_json(event_contract_path, event_contract())
    outputs.append(event_contract_path)

    maturity_summary_json = maturity_summary.copy()
    maturity_summary_json["analysis_as_of"] = maturity_summary_json["analysis_as_of"].astype(str)
    summary = {
        "version": VERSION,
        "seed": args.seed,
        "days": args.days,
        "products": [product.name for product in PRODUCTS],
        "quality": quality,
        "portfolio_conversion": portfolio_conversion(silver),
        "forecast_evaluations": forecast_rows,
        "analysis_as_of": {
            product: str(cutoff) for product, cutoff in analysis_as_of_by_product.items()
        },
        "forecast_gate": {
            "approved": int(forecast_frame["approved"].sum()),
            "withheld": int((~forecast_frame["approved"]).sum()),
        },
        "dau_definition_migration": migration_summary.to_dict(orient="records"),
        "retention_maturity": maturity_summary_json.to_dict(orient="records"),
        "activity_retention": retention_overall.to_dict(orient="records"),
        "revenue_reconciliation": reconciliation.to_dict(orient="records"),
    }
    summary_path = out / "reference_summary.json"
    _write_json(summary_path, summary)
    outputs.append(summary_path)

    # DuckDB is an operational convenience. The manifest focuses on portable
    # tabular/JSON evidence so hashes are comparable across platforms.
    manifest = write_manifest(outputs, root=out, output=out / "MANIFEST.json")
    print(json.dumps({**summary, "manifest_artifacts": manifest["artifact_count"]}, indent=2))


if __name__ == "__main__":
    main()
