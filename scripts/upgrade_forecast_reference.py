from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

import pandas as pd

from product_analytics.forecasting import (
    evaluate_forecast_plan,
    forecast_decision_contract,
    forecast_reconciliation,
    mature_metric_history,
    rolling_origin_seasonal_naive,
)
from product_analytics.provenance import write_manifest


VERSION = "0.34.0"
FORECAST_METRICS = ("dau", "revenue_gbp", "paid_subscription")


def _write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def upgrade_forecast_reference(root: Path) -> dict[str, object]:
    required = [
        root / "gold_daily_metrics.csv",
        root / "silver_events.csv",
        root / "reference_summary.json",
        root / "MANIFEST.json",
    ]
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"Base reference is incomplete: {missing}")

    gold = pd.read_csv(root / "gold_daily_metrics.csv")
    gold["date"] = pd.to_datetime(gold["date"], errors="raise").dt.date
    silver = pd.read_csv(root / "silver_events.csv")
    silver["event_ts"] = pd.to_datetime(silver["event_ts"], utc=True, errors="raise")

    evaluations: list[dict[str, object]] = []
    backtest_parts: list[pd.DataFrame] = []
    reconciliation_parts: list[pd.DataFrame] = []
    analysis_as_of: dict[str, str] = {}

    for product in sorted(gold["product"].unique()):
        mature, cutoff = mature_metric_history(gold, silver, product)
        analysis_as_of[product] = str(cutoff)
        for metric in FORECAST_METRICS:
            metric_name = f"{product}:{metric}"
            backtest = rolling_origin_seasonal_naive(mature, metric)
            backtest.insert(0, "metric", metric_name)
            evaluation = evaluate_forecast_plan(metric_name, backtest)
            row = asdict(evaluation)
            row["observation_cutoff"] = str(cutoff)
            evaluations.append(row)
            backtest_parts.append(backtest)
            reconciliation_parts.append(forecast_reconciliation(metric_name, backtest))

    evaluation_frame = pd.DataFrame(evaluations).sort_values("metric").reset_index(drop=True)
    backtest_frame = pd.concat(backtest_parts, ignore_index=True).sort_values(
        ["metric", "origin_index", "horizon_day"]
    ).reset_index(drop=True)
    reconciliation_frame = pd.concat(reconciliation_parts, ignore_index=True).sort_values(
        ["metric", "origin_index"]
    ).reset_index(drop=True)
    contract = forecast_decision_contract()

    outputs = {
        "forecast_evaluations.csv": evaluation_frame,
        "forecast_backtest.csv": backtest_frame,
        "forecast_reconciliation.csv": reconciliation_frame,
    }
    for name, frame in outputs.items():
        frame.to_csv(root / name, index=False)
    _write_json(root / "forecast_contract.json", contract)

    summary_path = root / "reference_summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    summary["version"] = VERSION
    summary["analysis_as_of"] = analysis_as_of
    summary["forecast_evaluations"] = evaluation_frame.to_dict(orient="records")
    summary["forecast_contract"] = contract
    summary["forecast_gate"] = {
        "approved": int(evaluation_frame["approved"].sum()),
        "withheld": int((~evaluation_frame["approved"]).sum()),
        "approved_metrics": evaluation_frame.loc[evaluation_frame["approved"], "metric"].tolist(),
    }
    summary["forecast_reconciliation"] = reconciliation_frame.to_dict(orient="records")
    _write_json(summary_path, summary)

    previous_manifest = json.loads((root / "MANIFEST.json").read_text(encoding="utf-8"))
    artifact_names = {item["path"] for item in previous_manifest["artifacts"]}
    artifact_names.update(
        {
            "forecast_evaluations.csv",
            "forecast_backtest.csv",
            "forecast_reconciliation.csv",
            "forecast_contract.json",
            "reference_summary.json",
        }
    )
    paths = [root / name for name in sorted(artifact_names)]
    manifest = write_manifest(paths, root=root, output=root / "MANIFEST.json")

    return {
        "version": VERSION,
        "approved": int(evaluation_frame["approved"].sum()),
        "withheld": int((~evaluation_frame["approved"]).sum()),
        "approved_metrics": evaluation_frame.loc[evaluation_frame["approved"], "metric"].tolist(),
        "manifest_artifacts": int(manifest["artifact_count"]),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Upgrade a base reference with v0.34 forecast decision evidence")
    parser.add_argument("root", nargs="?", default="build/reference")
    args = parser.parse_args()
    result = upgrade_forecast_reference(Path(args.root))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
