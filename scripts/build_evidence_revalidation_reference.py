from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path

import pandas as pd

from product_analytics.evidence_invalidation import (
    FRESH,
    build_reference_graph,
    canonical_sha256,
    propagate_invalidation,
    root_fingerprints,
    serialise_graph,
)
from product_analytics.evidence_revalidation import (
    NOOP,
    READY,
    REVALIDATED,
    apply_revalidation,
    complete_plan,
    plan_revalidation,
    verify_revalidated_freshness,
)
from product_analytics.forecasting import (
    evaluate_forecast_plan,
    mature_metric_history,
    rolling_origin_seasonal_naive,
)
from product_analytics.migration_governance import classify_event_contract_change


VERSION = "0.42.0"
PRICING_CHAIN = {"experiment:pricing", "impact:pricing", "authorisation:pricing"}


def _read_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _candidate_dau_forecasts(
    gold: pd.DataFrame,
    silver: pd.DataFrame,
) -> tuple[pd.DataFrame, str]:
    candidate = gold.copy()
    candidate["dau"] = candidate["dau_legacy_any_event"]
    metric_rows = candidate[["product", "date", "dau"]].copy()
    metric_rows["date"] = metric_rows["date"].astype(str)
    metric_rows = metric_rows.sort_values(["product", "date"]).reset_index(drop=True)
    metric_digest = canonical_sha256(metric_rows.to_dict(orient="records"))

    rows: list[dict[str, object]] = []
    for product in sorted(candidate["product"].unique()):
        history, cutoff = mature_metric_history(candidate, silver, product)
        backtest = rolling_origin_seasonal_naive(history, "dau")
        evaluation = evaluate_forecast_plan(f"{product}:dau", backtest)
        row = asdict(evaluation)
        row["observation_cutoff"] = str(cutoff)
        rows.append(row)
    return pd.DataFrame(rows).sort_values("metric").reset_index(drop=True), metric_digest


def _semantic_replacements(
    *,
    baseline_nodes,
    candidate_roots: dict[str, str],
    candidate_forecasts: pd.DataFrame,
) -> tuple[dict[str, str], dict[str, str]]:
    baseline = {node.node_id: node for node in baseline_nodes}
    fingerprints: dict[str, str] = {
        "semantic:dau": candidate_roots["semantic:dau"],
        "metric:dau": canonical_sha256(
            {
                "metric": "dau",
                "producer_surface": candidate_roots["contract:producer_shape"],
                "semantic_surface": candidate_roots["semantic:dau"],
            }
        ),
    }
    actions: dict[str, str] = {
        "semantic:dau": baseline["semantic:dau"].baseline_action,
        "metric:dau": baseline["metric:dau"].baseline_action,
    }

    for row in candidate_forecasts.to_dict(orient="records"):
        metric = str(row["metric"])
        product = metric.split(":", 1)[0]
        approved = bool(row["approved"])
        forecast_id = f"forecast:{metric}"
        planning_id = f"planning:{metric}"
        forecast_action = "APPROVE" if approved else "WITHHOLD"
        fingerprints[forecast_id] = canonical_sha256(row)
        actions[forecast_id] = forecast_action
        fingerprints[planning_id] = canonical_sha256(
            {
                "product": product,
                "metric": "dau",
                "forecast_action": forecast_action,
            }
        )
        actions[planning_id] = "PLAN" if approved else "WITHHOLD"
    return fingerprints, actions


def build_reference(base_dir: Path, output_dir: Path) -> dict[str, object]:
    required = [
        "event_contract.json",
        "migration_proposals.json",
        "migration_decisions.json",
        "forecast_evaluations.csv",
        "migration_forecast_impact.csv",
        "gold_daily_metrics.csv",
        "silver_events.csv",
        "pricing_experiment_decision.json",
        "pricing_impact_decision.json",
    ]
    missing = [name for name in required if not (base_dir / name).is_file()]
    if missing:
        raise FileNotFoundError(f"Base controlled evidence is incomplete: {missing}")

    current = _read_json(base_dir / "event_contract.json")
    proposals = _read_json(base_dir / "migration_proposals.json")
    migration = _read_json(base_dir / "migration_decisions.json")
    experiment = _read_json(base_dir / "pricing_experiment_decision.json")
    impact = _read_json(base_dir / "pricing_impact_decision.json")
    if not all(isinstance(item, dict) for item in (current, proposals, migration, experiment, impact)):
        raise TypeError("Controlled evidence JSON inputs must be objects")

    forecasts = pd.read_csv(base_dir / "forecast_evaluations.csv")
    baseline_nodes = build_reference_graph(
        event_contract_payload=current,
        forecast_rows=forecasts.to_dict(orient="records"),
        experiment_payload=experiment,
        impact_payload=impact,
    )
    baseline_by_id = {node.node_id: node for node in baseline_nodes}
    migration_actions = {
        str(item["proposal"]): str(item["action"])
        for item in migration.get("decisions", [])
    }

    gold = pd.read_csv(base_dir / "gold_daily_metrics.csv")
    gold["date"] = pd.to_datetime(gold["date"], errors="raise").dt.date
    silver = pd.read_csv(base_dir / "silver_events.csv")
    silver["event_ts"] = pd.to_datetime(silver["event_ts"], utc=True, errors="raise")
    candidate_forecasts, candidate_metric_digest = _candidate_dau_forecasts(gold, silver)

    output_dir.mkdir(parents=True, exist_ok=True)
    candidate_forecasts.to_csv(output_dir / "semantic_candidate_forecasts.csv", index=False)

    scenarios = [
        ("additive_noop", "add_optional_country", False),
        ("semantic_silent_replacement", "broaden_dau_to_any_event", False),
        ("semantic_explicit_versioned_adoption", "broaden_dau_to_any_event", True),
        ("breaking_producer_change", "rename_required_event_id", True),
    ]
    summary_rows: list[dict[str, object]] = []
    evidence: dict[str, object] = {}
    semantic_graph: tuple | None = None

    for scenario, proposal_name, explicit_adoption in scenarios:
        proposal = proposals[proposal_name]
        if not isinstance(proposal, dict):
            raise TypeError(f"Proposal {proposal_name} must be a JSON object")
        classification = classify_event_contract_change(current, proposal)
        candidate_roots = root_fingerprints(proposal)
        invalidation = propagate_invalidation(baseline_nodes, candidate_roots)
        plan = plan_revalidation(
            proposal=proposal_name,
            classification=classification.classification,
            migration_action=migration_actions[proposal_name],
            invalidation_records=invalidation,
            explicit_semantic_adoption=explicit_adoption,
        )
        initial_stale = sum(record.status != FRESH for record in invalidation)
        initial_fresh = len(baseline_nodes) - initial_stale
        final_fresh = initial_fresh
        final_stale = initial_stale
        final_status = plan.status
        replacements: dict[str, str] = {}
        replacement_actions: dict[str, str] = {}
        reused_exact = len(plan.reused_node_ids)
        metric_rows_recomputed = 0
        forecast_series_recomputed = 0
        planning_decisions_recomputed = 0
        pricing_chain_recomputed = 0
        adopted_metric_digest: str | None = None

        if plan.status == NOOP:
            updated = apply_revalidation(
                baseline_nodes=baseline_nodes,
                plan=plan,
                replacement_fingerprints={},
                replacement_actions={},
            )
            if updated != baseline_nodes:
                raise AssertionError("NOOP plan changed baseline graph")
            final_fresh = len(updated)
            final_stale = 0
        elif plan.status == READY:
            if proposal_name != "broaden_dau_to_any_event" or not explicit_adoption:
                raise AssertionError("Only the explicit DAU semantic adoption is executable")
            replacements, replacement_actions = _semantic_replacements(
                baseline_nodes=baseline_nodes,
                candidate_roots=candidate_roots,
                candidate_forecasts=candidate_forecasts,
            )
            if set(replacements) != set(plan.rebuild_node_ids):
                raise AssertionError("Selective rebuild set differs from planned stale-node set")
            updated = apply_revalidation(
                baseline_nodes=baseline_nodes,
                plan=plan,
                replacement_fingerprints=replacements,
                replacement_actions=replacement_actions,
            )
            verification = verify_revalidated_freshness(
                revalidated_nodes=updated,
                candidate_root_fingerprints=candidate_roots,
            )
            if any(record.status != FRESH for record in verification):
                raise AssertionError("Revalidated graph did not become fully fresh")
            updated_by_id = {node.node_id: node for node in updated}
            for node_id in plan.reused_node_ids:
                if updated_by_id[node_id] != baseline_by_id[node_id]:
                    raise AssertionError(f"Unaffected node changed during selective rebuild: {node_id}")
            semantic_graph = updated
            final_status = complete_plan(plan).status
            final_fresh = len(updated)
            final_stale = 0
            metric_rows_recomputed = int(len(gold))
            forecast_series_recomputed = int(len(candidate_forecasts))
            planning_decisions_recomputed = int(len(candidate_forecasts))
            adopted_metric_digest = candidate_metric_digest

        summary_rows.append(
            {
                "scenario": scenario,
                "proposal": proposal_name,
                "classification": classification.classification,
                "original_migration_action": migration_actions[proposal_name],
                "explicit_semantic_adoption": explicit_adoption,
                "plan_status": plan.status,
                "final_status": final_status,
                "initial_fresh_nodes": initial_fresh,
                "initial_stale_nodes": initial_stale,
                "revalidated_nodes": len(plan.rebuild_node_ids) if final_status == REVALIDATED else 0,
                "reused_nodes": reused_exact,
                "final_fresh_nodes": final_fresh,
                "final_stale_nodes": final_stale,
                "metric_rows_recomputed": metric_rows_recomputed,
                "forecast_series_recomputed": forecast_series_recomputed,
                "planning_decisions_recomputed": planning_decisions_recomputed,
                "pricing_chain_recomputed": pricing_chain_recomputed,
                "blocked_reason": plan.blocked_reason or "",
            }
        )
        evidence[scenario] = {
            "proposal": proposal_name,
            "classification": classification.classification,
            "original_migration_action": migration_actions[proposal_name],
            "explicit_semantic_adoption": explicit_adoption,
            "plan_status": plan.status,
            "final_status": final_status,
            "initial_stale_node_ids": list(plan.initial_stale_node_ids),
            "revalidation_steps": [asdict(step) for step in plan.steps],
            "reused_node_ids": list(plan.reused_node_ids),
            "replacement_fingerprints": replacements,
            "replacement_actions": replacement_actions,
            "candidate_metric_data_sha256": adopted_metric_digest,
            "blocked_reason": plan.blocked_reason,
        }

    if semantic_graph is None:
        raise AssertionError("Explicit semantic revalidation did not execute")
    _write_json(
        output_dir / "semantic_revalidated_graph.json",
        {
            "version": VERSION,
            "proposal": "broaden_dau_to_any_event",
            "adoption_mode": "explicit_versioned_semantic_adoption",
            "original_silent_replacement_action": migration_actions["broaden_dau_to_any_event"],
            "metric_delta_tolerance_relaxed": False,
            "nodes": serialise_graph(semantic_graph),
        },
    )
    summary = pd.DataFrame(summary_rows)
    summary.to_csv(output_dir / "evidence_revalidation_summary.csv", index=False)
    _write_json(
        output_dir / "evidence_revalidation_evidence.json",
        {
            "version": VERSION,
            "base_reference_version": migration.get("version"),
            "policy": {
                "silent_semantic_replacement_can_be_repaired_by_recompute": False,
                "explicit_versioned_semantic_adoption_required": True,
                "migration_tolerance_relaxed": False,
                "breaking_producer_change_revalidatable_downstream": False,
                "unaffected_nodes_must_be_reused_exactly": True,
                "performance_claim": "deterministic work counts only; no latency or speedup claim",
            },
            "candidate_forecast_evidence_sha256": canonical_sha256(
                candidate_forecasts.to_dict(orient="records")
            ),
            "scenarios": evidence,
        },
    )

    semantic_row = summary.loc[
        summary["scenario"].eq("semantic_explicit_versioned_adoption")
    ].iloc[0]
    return {
        "version": VERSION,
        "scenarios": int(len(summary)),
        "semantic_initial_stale": int(semantic_row["initial_stale_nodes"]),
        "semantic_revalidated_nodes": int(semantic_row["revalidated_nodes"]),
        "semantic_reused_nodes": int(semantic_row["reused_nodes"]),
        "semantic_final_stale": int(semantic_row["final_stale_nodes"]),
        "candidate_forecast_series": int(len(candidate_forecasts)),
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build v0.42 selective evidence revalidation reference"
    )
    parser.add_argument("--base-dir", default="build/reference")
    parser.add_argument("--output-dir", default="build/evidence-revalidation")
    args = parser.parse_args()
    result = build_reference(Path(args.base_dir), Path(args.output_dir))
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
