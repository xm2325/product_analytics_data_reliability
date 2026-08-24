from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from datetime import timedelta
from pathlib import Path

import pandas as pd

from product_analytics.config import PRODUCTS
from product_analytics.contracts import event_contract
from product_analytics.evidence_planning import certification_evidence_plan, select_evidence_plan
from product_analytics.forecasting import evaluate_forecast, mature_metric_history, seasonal_naive
from product_analytics.freshness import (
    DEFAULT_LATE_ARRIVAL_POLICY,
    DEFAULT_WATERMARK_CANDIDATES,
    DEFAULT_WATERMARK_RISK_BUDGET,
    late_after_watermark_snapshot,
    late_arrival_contract,
    late_arrival_summary,
    metric_revision_report,
    revision_summary,
    rolling_watermark_backtest,
    select_stable_watermark_policy,
    select_watermark_policy,
    watermark_policy_grid,
    watermark_stability_summary,
)
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
from product_analytics.uncertainty import (
    DEFAULT_FAMILY_ALPHA,
    select_certified_watermark_policy,
    watermark_uncertainty_grid,
    watermark_uncertainty_summary,
)


VERSION = "0.31.0"


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
    if args.days < 70:
        raise SystemExit("--days must be at least 70 so forecast and rolling freshness backtests are estimable")

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
    for name, frame in {
        "dau_definition_migration.csv": migration,
        "dau_definition_migration_summary.csv": migration_summary,
    }.items():
        path = out / name
        frame.to_csv(path, index=False)
        outputs.append(path)

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

    reporting_date = max(pd.Timestamp(value).date() for value in analysis_as_of_by_product.values())
    processing_as_of = pd.Timestamp(reporting_date, tz="UTC") + timedelta(days=1) - timedelta(microseconds=1)

    arrival_summary = late_arrival_summary(silver, DEFAULT_LATE_ARRIVAL_POLICY)
    late_finalized_events = late_after_watermark_snapshot(silver, processing_as_of, DEFAULT_LATE_ARRIVAL_POLICY)
    revisions = metric_revision_report(silver, processing_as_of, DEFAULT_LATE_ARRIVAL_POLICY)
    revision_overall = revision_summary(revisions)
    for name, frame in {
        "late_arrival_summary.csv": arrival_summary,
        "watermark_late_events.csv": late_finalized_events,
        "watermark_metric_revisions.csv": revisions,
        "watermark_revision_summary.csv": revision_overall,
    }.items():
        path = out / name
        frame.to_csv(path, index=False)
        outputs.append(path)

    policy_grid = watermark_policy_grid(
        silver,
        processing_as_of,
        candidate_hours=DEFAULT_WATERMARK_CANDIDATES,
        budget=DEFAULT_WATERMARK_RISK_BUDGET,
    )
    policy_decision = select_watermark_policy(policy_grid, DEFAULT_WATERMARK_RISK_BUDGET)
    policy_grid_path = out / "watermark_policy_grid.csv"
    policy_grid.to_csv(policy_grid_path, index=False)
    outputs.append(policy_grid_path)
    policy_decision_path = out / "watermark_policy_decision.json"
    _write_json(policy_decision_path, policy_decision)
    outputs.append(policy_decision_path)

    rolling_snapshots = [
        processing_as_of - timedelta(days=7 * weeks_back)
        for weeks_back in range(8, -1, -1)
    ]
    rolling_grid, rolling_windows = rolling_watermark_backtest(
        silver,
        processing_snapshots=rolling_snapshots,
        candidate_hours=DEFAULT_WATERMARK_CANDIDATES,
        budget=DEFAULT_WATERMARK_RISK_BUDGET,
    )
    stability = watermark_stability_summary(rolling_grid)
    stable_decision = select_stable_watermark_policy(stability, DEFAULT_WATERMARK_RISK_BUDGET)
    for name, frame in {
        "watermark_rolling_grid.csv": rolling_grid,
        "watermark_rolling_windows.csv": rolling_windows,
        "watermark_stability_summary.csv": stability,
    }.items():
        path = out / name
        frame.to_csv(path, index=False)
        outputs.append(path)
    stable_decision_path = out / "watermark_stability_decision.json"
    _write_json(stable_decision_path, stable_decision)
    outputs.append(stable_decision_path)

    uncertainty_grid, uncertainty_contract = watermark_uncertainty_grid(
        rolling_grid,
        budget=DEFAULT_WATERMARK_RISK_BUDGET,
        family_alpha=DEFAULT_FAMILY_ALPHA,
    )
    uncertainty_summary = watermark_uncertainty_summary(uncertainty_grid)
    certification_decision = select_certified_watermark_policy(uncertainty_summary, uncertainty_contract)
    for name, frame in {
        "watermark_uncertainty_grid.csv": uncertainty_grid,
        "watermark_uncertainty_summary.csv": uncertainty_summary,
    }.items():
        path = out / name
        frame.to_csv(path, index=False)
        outputs.append(path)
    uncertainty_contract_path = out / "watermark_uncertainty_contract.json"
    _write_json(uncertainty_contract_path, uncertainty_contract)
    outputs.append(uncertainty_contract_path)
    certification_decision_path = out / "watermark_certification_decision.json"
    _write_json(certification_decision_path, certification_decision)
    outputs.append(certification_decision_path)

    # v0.31: translate the v0.29 no-certification result into a prospective
    # cycle-stable evidence plan without loosening confidence, risk budgets or hard gates.
    evidence_plan, evidence_plan_contract = certification_evidence_plan(
        rolling_grid,
        family_alpha=DEFAULT_FAMILY_ALPHA,
        budget=DEFAULT_WATERMARK_RISK_BUDGET,
    )
    evidence_plan_decision = select_evidence_plan(evidence_plan)
    evidence_plan_path = out / "watermark_evidence_plan.csv"
    evidence_plan.to_csv(evidence_plan_path, index=False)
    outputs.append(evidence_plan_path)
    evidence_plan_contract_path = out / "watermark_evidence_plan_contract.json"
    _write_json(evidence_plan_contract_path, evidence_plan_contract)
    outputs.append(evidence_plan_contract_path)
    evidence_plan_decision_path = out / "watermark_evidence_plan_decision.json"
    _write_json(evidence_plan_decision_path, evidence_plan_decision)
    outputs.append(evidence_plan_decision_path)

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

    arrival_contract = late_arrival_contract(processing_as_of, DEFAULT_LATE_ARRIVAL_POLICY)
    arrival_contract_path = out / "late_arrival_contract.json"
    _write_json(arrival_contract_path, arrival_contract)
    outputs.append(arrival_contract_path)

    maturity_summary_json = maturity_summary.copy()
    maturity_summary_json["analysis_as_of"] = maturity_summary_json["analysis_as_of"].astype(str)
    rolling_windows_json = rolling_windows.copy()
    rolling_windows_json["processing_as_of"] = rolling_windows_json["processing_as_of"].astype(str)
    summary = {
        "version": VERSION,
        "seed": args.seed,
        "days": args.days,
        "products": [product.name for product in PRODUCTS],
        "quality": quality,
        "portfolio_conversion": portfolio_conversion(silver),
        "forecast_evaluations": forecast_rows,
        "analysis_as_of": {product: str(cutoff) for product, cutoff in analysis_as_of_by_product.items()},
        "forecast_gate": {
            "approved": int(forecast_frame["approved"].sum()),
            "withheld": int((~forecast_frame["approved"]).sum()),
        },
        "dau_definition_migration": migration_summary.to_dict(orient="records"),
        "retention_maturity": maturity_summary_json.to_dict(orient="records"),
        "activity_retention": retention_overall.to_dict(orient="records"),
        "processing_time": {
            "contract": arrival_contract,
            "late_beyond_watermark_events": int(arrival_summary["late_beyond_watermark"].sum()),
            "late_missing_from_finalized_snapshot": int(len(late_finalized_events)),
            "revised_finalized_metric_cells": int(revisions["changed_after_watermark"].sum()),
            "revision_summary": revision_overall.to_dict(orient="records"),
            "point_in_time_watermark_calibration": policy_decision,
            "watermark_policy_grid": policy_grid.to_dict(orient="records"),
            "rolling_backtest_windows": rolling_windows_json.to_dict(orient="records"),
            "watermark_stability_summary": stability.to_dict(orient="records"),
            "watermark_stability_decision": stable_decision,
            "watermark_uncertainty_contract": uncertainty_contract,
            "watermark_uncertainty_summary": uncertainty_summary.to_dict(orient="records"),
            "watermark_certification_decision": certification_decision,
            "watermark_evidence_plan_contract": evidence_plan_contract,
            "watermark_evidence_plan": evidence_plan.to_dict(orient="records"),
            "watermark_evidence_plan_decision": evidence_plan_decision,
        },
        "revenue_reconciliation": reconciliation.to_dict(orient="records"),
    }
    summary_path = out / "reference_summary.json"
    _write_json(summary_path, summary)
    outputs.append(summary_path)

    manifest = write_manifest(outputs, root=out, output=out / "MANIFEST.json")
    print(json.dumps({**summary, "manifest_artifacts": manifest["artifact_count"]}, indent=2))


if __name__ == "__main__":
    main()
