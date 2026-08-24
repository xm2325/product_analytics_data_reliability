from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

import pandas as pd

from product_analytics.contracts import event_contract
from product_analytics.forecasting import (
    evaluate_forecast_plan,
    mature_metric_history,
    rolling_origin_seasonal_naive,
)
from product_analytics.migration_governance import (
    MIGRATION_TOLERANCE,
    classify_event_contract_change,
    contract_registry,
    dau_shadow_replay,
    decide_migration,
    migration_proposals,
    summarise_dau_shadow_replay,
)
from product_analytics.provenance import write_manifest


VERSION = "0.35.0"


def _write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _forecast_impact(gold: pd.DataFrame, silver: pd.DataFrame) -> pd.DataFrame:
    candidate_gold = gold.copy()
    candidate_gold["dau"] = candidate_gold["dau_legacy_any_event"]
    rows: list[dict[str, object]] = []
    for product in sorted(gold["product"].unique()):
        current_history, cutoff = mature_metric_history(gold, silver, product)
        candidate_history, candidate_cutoff = mature_metric_history(candidate_gold, silver, product)
        if cutoff != candidate_cutoff:
            raise AssertionError("Metric semantics must not change the observation boundary")
        current_bt = rolling_origin_seasonal_naive(current_history, "dau")
        candidate_bt = rolling_origin_seasonal_naive(candidate_history, "dau")
        current_eval = evaluate_forecast_plan(f"{product}:dau", current_bt)
        candidate_eval = evaluate_forecast_plan(f"{product}:dau:any_event_candidate", candidate_bt)
        rows.append(
            {
                "product": product,
                "observation_cutoff": str(cutoff),
                "current_wape": current_eval.wape,
                "candidate_wape": candidate_eval.wape,
                "current_benchmark_wape": current_eval.benchmark_wape,
                "candidate_benchmark_wape": candidate_eval.benchmark_wape,
                "current_interval_coverage": current_eval.interval_coverage,
                "candidate_interval_coverage": candidate_eval.interval_coverage,
                "current_approved": current_eval.approved,
                "candidate_approved": candidate_eval.approved,
                "eligibility_changed": current_eval.approved != candidate_eval.approved,
            }
        )
    return pd.DataFrame(rows).sort_values("product").reset_index(drop=True)


def upgrade_contract_reference(root: Path) -> dict[str, object]:
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

    registry = contract_registry()
    replay = dau_shadow_replay(gold)
    impact = summarise_dau_shadow_replay(replay)
    forecast_impact = _forecast_impact(gold, silver)

    current = event_contract()
    proposals = migration_proposals()
    decisions = []
    for name, proposal in sorted(proposals.items()):
        classification = classify_event_contract_change(current, proposal)
        if name == "broaden_dau_to_any_event":
            max_delta = float(impact["portfolio_weighted_dau_delta_pct"].abs().max())
            eligibility_changed = bool(forecast_impact["eligibility_changed"].any())
        elif name == "add_optional_country":
            max_delta = 0.0
            eligibility_changed = False
        else:
            max_delta = 0.0
            eligibility_changed = False
        decisions.append(
            asdict(
                decide_migration(
                    name,
                    classification,
                    max_abs_metric_delta_pct=max_delta,
                    forecast_eligibility_changed=eligibility_changed,
                )
            )
        )

    _write_json(root / "contract_registry.json", registry)
    _write_json(
        root / "migration_proposals.json",
        {name: proposal for name, proposal in sorted(proposals.items())},
    )
    replay.to_csv(root / "migration_replay.csv", index=False)
    impact.to_csv(root / "metric_change_impact.csv", index=False)
    forecast_impact.to_csv(root / "migration_forecast_impact.csv", index=False)
    _write_json(
        root / "migration_decisions.json",
        {
            "version": VERSION,
            "metric_delta_tolerance": MIGRATION_TOLERANCE,
            "decision_rule": (
                "existing producers compatible AND shadow metric movement within tolerance "
                "AND forecast eligibility unchanged"
            ),
            "decisions": decisions,
        },
    )

    summary_path = root / "reference_summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    summary["version"] = VERSION
    summary["contract_migration"] = {
        "metric_delta_tolerance": MIGRATION_TOLERANCE,
        "decisions": decisions,
        "metric_change_impact": impact.to_dict(orient="records"),
        "forecast_impact": forecast_impact.to_dict(orient="records"),
    }
    _write_json(summary_path, summary)

    previous_manifest = json.loads((root / "MANIFEST.json").read_text(encoding="utf-8"))
    artifact_names = {item["path"] for item in previous_manifest["artifacts"]}
    artifact_names.update(
        {
            "contract_registry.json",
            "migration_proposals.json",
            "migration_replay.csv",
            "metric_change_impact.csv",
            "migration_forecast_impact.csv",
            "migration_decisions.json",
            "reference_summary.json",
        }
    )
    paths = [root / name for name in sorted(artifact_names)]
    manifest = write_manifest(paths, root=root, output=root / "MANIFEST.json")

    actions = {item["proposal"]: item["action"] for item in decisions}
    return {
        "version": VERSION,
        "actions": actions,
        "max_semantic_dau_delta_pct": float(impact["portfolio_weighted_dau_delta_pct"].abs().max()),
        "forecast_eligibility_changes": int(forecast_impact["eligibility_changed"].sum()),
        "manifest_artifacts": int(manifest["artifact_count"]),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Upgrade a v0.34 reference with v0.35 contract migration evidence")
    parser.add_argument("root", nargs="?", default="build/reference")
    args = parser.parse_args()
    result = upgrade_contract_reference(Path(args.root))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
