from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

import pandas as pd

from product_analytics.contracts import event_contract
from product_analytics.forecasting import evaluate_forecast_plan, mature_metric_history, rolling_origin_seasonal_naive
from product_analytics.migration_governance import (
    MIGRATION_TOLERANCE,
    classify_event_contract_change,
    dau_shadow_replay,
    decide_migration,
    migration_proposals,
    summarise_dau_shadow_replay,
)


def _assert_close(left: float, right: float, tolerance: float = 1e-12) -> None:
    if abs(float(left) - float(right)) > tolerance:
        raise AssertionError(f"Expected {left!r} ~= {right!r}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Independently recompute v0.35 migration governance evidence")
    parser.add_argument("root", nargs="?", default="build/reference")
    args = parser.parse_args()
    root = Path(args.root)

    gold = pd.read_csv(root / "gold_daily_metrics.csv")
    gold["date"] = pd.to_datetime(gold["date"], errors="raise").dt.date
    silver = pd.read_csv(root / "silver_events.csv")
    silver["event_ts"] = pd.to_datetime(silver["event_ts"], utc=True, errors="raise")
    stored_replay = pd.read_csv(root / "migration_replay.csv")
    stored_impact = pd.read_csv(root / "metric_change_impact.csv")
    stored_forecast = pd.read_csv(root / "migration_forecast_impact.csv")
    stored_decisions = json.loads((root / "migration_decisions.json").read_text(encoding="utf-8"))

    replay = dau_shadow_replay(gold)
    impact = summarise_dau_shadow_replay(replay)
    if len(replay) != len(stored_replay):
        raise AssertionError("migration replay row count changed")
    for column in ("current_dau", "candidate_dau", "dau_delta_users", "paid_delta", "revenue_delta_gbp"):
        if not pd.to_numeric(replay[column]).reset_index(drop=True).equals(
            pd.to_numeric(stored_replay[column]).reset_index(drop=True)
        ):
            raise AssertionError(f"migration replay mismatch in {column}")

    merged_impact = impact.merge(stored_impact, on="product", suffixes=("_recomputed", "_stored"), validate="one_to_one")
    for column in (
        "portfolio_weighted_dau_delta_pct",
        "max_daily_abs_dau_delta_pct",
        "max_abs_paid_delta",
        "max_abs_revenue_delta_gbp",
    ):
        for _, row in merged_impact.iterrows():
            _assert_close(row[f"{column}_recomputed"], row[f"{column}_stored"])

    candidate_gold = gold.copy()
    candidate_gold["dau"] = candidate_gold["dau_legacy_any_event"]
    recomputed_forecast = []
    for product in sorted(gold["product"].unique()):
        current_history, cutoff = mature_metric_history(gold, silver, product)
        candidate_history, candidate_cutoff = mature_metric_history(candidate_gold, silver, product)
        if cutoff != candidate_cutoff:
            raise AssertionError("observation cutoff changed under metric migration")
        current_eval = evaluate_forecast_plan(
            f"{product}:dau", rolling_origin_seasonal_naive(current_history, "dau")
        )
        candidate_eval = evaluate_forecast_plan(
            f"{product}:dau:any_event_candidate",
            rolling_origin_seasonal_naive(candidate_history, "dau"),
        )
        recomputed_forecast.append(
            {
                "product": product,
                "current_wape": current_eval.wape,
                "candidate_wape": candidate_eval.wape,
                "current_approved": current_eval.approved,
                "candidate_approved": candidate_eval.approved,
                "eligibility_changed": current_eval.approved != candidate_eval.approved,
            }
        )
    recomputed_forecast = pd.DataFrame(recomputed_forecast)
    merged_forecast = recomputed_forecast.merge(stored_forecast, on="product", suffixes=("_recomputed", "_stored"), validate="one_to_one")
    for _, row in merged_forecast.iterrows():
        _assert_close(row["current_wape_recomputed"], row["current_wape_stored"])
        _assert_close(row["candidate_wape_recomputed"], row["candidate_wape_stored"])
        for column in ("current_approved", "candidate_approved", "eligibility_changed"):
            if bool(row[f"{column}_recomputed"]) != bool(row[f"{column}_stored"]):
                raise AssertionError(f"forecast migration mismatch in {column}")

    current = event_contract()
    proposals = migration_proposals()
    max_semantic_delta = float(impact["portfolio_weighted_dau_delta_pct"].abs().max())
    eligibility_changed = bool(recomputed_forecast["eligibility_changed"].any())
    recomputed_decisions = []
    for name, proposal in sorted(proposals.items()):
        classification = classify_event_contract_change(current, proposal)
        decision = decide_migration(
            name,
            classification,
            max_abs_metric_delta_pct=max_semantic_delta if name == "broaden_dau_to_any_event" else 0.0,
            forecast_eligibility_changed=eligibility_changed if name == "broaden_dau_to_any_event" else False,
        )
        recomputed_decisions.append(asdict(decision))

    if stored_decisions["metric_delta_tolerance"] != MIGRATION_TOLERANCE:
        raise AssertionError("migration tolerance changed")
    if recomputed_decisions != stored_decisions["decisions"]:
        raise AssertionError("migration decisions do not match independent recomputation")

    actions = {row["proposal"]: row["action"] for row in recomputed_decisions}
    if actions != {
        "add_optional_country": "APPROVE",
        "broaden_dau_to_any_event": "WITHHOLD",
        "rename_required_event_id": "WITHHOLD",
    }:
        raise AssertionError(f"unexpected reference actions: {actions}")

    print(
        "Contract migration validation passed: "
        f"{len(replay)} replay rows, {len(recomputed_forecast)} forecast comparisons, actions={actions}"
    )


if __name__ == "__main__":
    main()
