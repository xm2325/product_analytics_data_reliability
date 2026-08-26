from __future__ import annotations

import argparse
from dataclasses import asdict
import json
import math
from pathlib import Path

import pandas as pd

from product_analytics.evidence_invalidation import (
    FRESH,
    EvidenceNode,
    build_reference_graph,
    canonical_sha256,
    propagate_invalidation,
    root_fingerprints,
)
from product_analytics.forecasting import (
    evaluate_forecast_plan,
    mature_metric_history,
    rolling_origin_seasonal_naive,
)
from product_analytics.migration_governance import classify_event_contract_change


VERSION = "0.42.0"
AFFECTED_DAU_NODES = {
    "semantic:dau",
    "metric:dau",
    "forecast:file_transfer:dau",
    "forecast:notes_app:dau",
    "forecast:photo_editor:dau",
    "planning:file_transfer:dau",
    "planning:notes_app:dau",
    "planning:photo_editor:dau",
}
PRICING_CHAIN = {"experiment:pricing", "impact:pricing", "authorisation:pricing"}


def _read_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def _bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"true", "1"}:
        return True
    if text in {"false", "0"}:
        return False
    raise AssertionError(f"Invalid boolean {value!r}")


def _assert_close(actual: float, expected: float, *, label: str, tol: float = 1e-12) -> None:
    if not math.isclose(float(actual), float(expected), rel_tol=0.0, abs_tol=tol):
        raise AssertionError(f"{label}: expected {expected}, got {actual}")


def _candidate_forecasts(gold: pd.DataFrame, silver: pd.DataFrame) -> pd.DataFrame:
    candidate = gold.copy()
    candidate["dau"] = candidate["dau_legacy_any_event"]
    rows: list[dict[str, object]] = []
    for product in sorted(candidate["product"].unique()):
        history, cutoff = mature_metric_history(candidate, silver, product)
        backtest = rolling_origin_seasonal_naive(history, "dau")
        evaluation = evaluate_forecast_plan(f"{product}:dau", backtest)
        row = asdict(evaluation)
        row["observation_cutoff"] = str(cutoff)
        rows.append(row)
    return pd.DataFrame(rows).sort_values("metric").reset_index(drop=True)


def _node_from_json(payload: dict[str, object]) -> EvidenceNode:
    return EvidenceNode(
        node_id=str(payload["node_id"]),
        kind=str(payload["kind"]),
        dependencies=tuple(payload["dependencies"]),
        fingerprint=str(payload["fingerprint"]),
        baseline_action=str(payload["baseline_action"]),
    )


def validate(base_dir: Path, output_dir: Path) -> None:
    current = _read_json(base_dir / "event_contract.json")
    proposals = _read_json(base_dir / "migration_proposals.json")
    migration = _read_json(base_dir / "migration_decisions.json")
    experiment = _read_json(base_dir / "pricing_experiment_decision.json")
    impact = _read_json(base_dir / "pricing_impact_decision.json")
    evidence = _read_json(output_dir / "evidence_revalidation_evidence.json")
    graph_payload = _read_json(output_dir / "semantic_revalidated_graph.json")
    if not all(isinstance(item, dict) for item in (current, proposals, migration, experiment, impact, evidence, graph_payload)):
        raise AssertionError("Expected JSON objects")
    if evidence.get("version") != VERSION or graph_payload.get("version") != VERSION:
        raise AssertionError("v0.42 evidence version mismatch")

    policy = evidence.get("policy", {})
    expected_policy = {
        "silent_semantic_replacement_can_be_repaired_by_recompute": False,
        "explicit_versioned_semantic_adoption_required": True,
        "migration_tolerance_relaxed": False,
        "breaking_producer_change_revalidatable_downstream": False,
        "unaffected_nodes_must_be_reused_exactly": True,
        "performance_claim": "deterministic work counts only; no latency or speedup claim",
    }
    if policy != expected_policy:
        raise AssertionError(f"Unexpected revalidation policy: {policy}")
    if graph_payload.get("metric_delta_tolerance_relaxed") is not False:
        raise AssertionError("Semantic revalidation must not relax the migration tolerance")

    summary = pd.read_csv(output_dir / "evidence_revalidation_summary.csv", dtype=str, keep_default_na=False)
    expected_scenarios = {
        "additive_noop": ("NOOP", "NOOP", 0, 0, 16, 16, 0),
        "semantic_silent_replacement": (
            "BLOCKED_EXPLICIT_ADOPTION_REQUIRED",
            "BLOCKED_EXPLICIT_ADOPTION_REQUIRED",
            8,
            0,
            8,
            8,
            8,
        ),
        "semantic_explicit_versioned_adoption": ("READY", "REVALIDATED", 8, 8, 8, 16, 0),
        "breaking_producer_change": (
            "BLOCKED_PRODUCER_INCOMPATIBLE",
            "BLOCKED_PRODUCER_INCOMPATIBLE",
            13,
            0,
            3,
            3,
            13,
        ),
    }
    if set(summary["scenario"]) != set(expected_scenarios):
        raise AssertionError("Scenario set mismatch")
    for scenario, expected in expected_scenarios.items():
        row = summary.loc[summary["scenario"].eq(scenario)].iloc[0]
        actual = (
            row["plan_status"],
            row["final_status"],
            int(row["initial_stale_nodes"]),
            int(row["revalidated_nodes"]),
            int(row["reused_nodes"]),
            int(row["final_fresh_nodes"]),
            int(row["final_stale_nodes"]),
        )
        if actual != expected:
            raise AssertionError(f"{scenario}: expected {expected}, got {actual}")
        if int(row["pricing_chain_recomputed"]) != 0:
            raise AssertionError(f"{scenario}: pricing chain must not be reported as recomputed")

    semantic_row = summary.loc[
        summary["scenario"].eq("semantic_explicit_versioned_adoption")
    ].iloc[0]

    gold = pd.read_csv(base_dir / "gold_daily_metrics.csv")
    gold["date"] = pd.to_datetime(gold["date"], errors="raise").dt.date
    silver = pd.read_csv(base_dir / "silver_events.csv")
    silver["event_ts"] = pd.to_datetime(silver["event_ts"], utc=True, errors="raise")
    if int(semantic_row["metric_rows_recomputed"]) != len(gold):
        raise AssertionError("Semantic metric work count does not equal controlled Gold rows")
    if int(semantic_row["forecast_series_recomputed"]) != 3:
        raise AssertionError("Semantic revalidation must recompute exactly three DAU forecast series")
    if int(semantic_row["planning_decisions_recomputed"]) != 3:
        raise AssertionError("Semantic revalidation must recompute exactly three planning decisions")

    recomputed = _candidate_forecasts(gold, silver)
    stored = pd.read_csv(output_dir / "semantic_candidate_forecasts.csv")
    if list(stored.columns) != list(recomputed.columns) or len(stored) != len(recomputed):
        raise AssertionError("Candidate forecast evidence shape mismatch")
    for index in range(len(recomputed)):
        left = stored.iloc[index]
        right = recomputed.iloc[index]
        for column in stored.columns:
            if column in {"approved", "enough_backtest_gate", "absolute_accuracy_gate", "benchmark_gate", "interval_coverage_gate"}:
                if _bool(left[column]) != _bool(right[column]):
                    raise AssertionError(f"candidate forecast {index}/{column} mismatch")
            elif pd.api.types.is_numeric_dtype(recomputed[column]):
                _assert_close(left[column], right[column], label=f"candidate forecast {index}/{column}")
            else:
                if str(left[column]) != str(right[column]):
                    raise AssertionError(f"candidate forecast {index}/{column} mismatch")

    # Cross-check the newly recomputed candidate forecasts against the separately
    # validated v0.35 migration forecast evidence.
    migration_forecast = pd.read_csv(base_dir / "migration_forecast_impact.csv").set_index("product")
    for row in recomputed.to_dict(orient="records"):
        product = str(row["metric"]).split(":", 1)[0]
        frozen = migration_forecast.loc[product]
        _assert_close(row["wape"], frozen["candidate_wape"], label=f"{product} candidate WAPE")
        _assert_close(
            row["benchmark_wape"],
            frozen["candidate_benchmark_wape"],
            label=f"{product} candidate benchmark WAPE",
        )
        _assert_close(
            row["interval_coverage"],
            frozen["candidate_interval_coverage"],
            label=f"{product} candidate interval coverage",
        )
        if bool(row["approved"]) != _bool(frozen["candidate_approved"]):
            raise AssertionError(f"{product} candidate approval differs from frozen migration evidence")

    forecasts = pd.read_csv(base_dir / "forecast_evaluations.csv")
    baseline_nodes = build_reference_graph(
        event_contract_payload=current,
        forecast_rows=forecasts.to_dict(orient="records"),
        experiment_payload=experiment,
        impact_payload=impact,
    )
    baseline = {node.node_id: node for node in baseline_nodes}
    semantic_proposal = proposals["broaden_dau_to_any_event"]
    classification = classify_event_contract_change(current, semantic_proposal)
    if classification.classification != "SEMANTIC" or not classification.producer_compatible:
        raise AssertionError("Frozen semantic proposal classification changed")
    actions = {str(row["proposal"]): str(row["action"]) for row in migration["decisions"]}
    if actions["broaden_dau_to_any_event"] != "WITHHOLD":
        raise AssertionError("Original semantic silent replacement must remain WITHHOLD")

    candidate_roots = root_fingerprints(semantic_proposal)
    initial = propagate_invalidation(baseline_nodes, candidate_roots)
    stale_ids = {record.node_id for record in initial if record.status != FRESH}
    if stale_ids != AFFECTED_DAU_NODES:
        raise AssertionError(f"Initial semantic stale set changed: {sorted(stale_ids)}")

    stored_graph_nodes = tuple(_node_from_json(row) for row in graph_payload["nodes"])
    stored_graph = {node.node_id: node for node in stored_graph_nodes}
    if set(stored_graph) != set(baseline):
        raise AssertionError("Revalidated graph node set changed")

    expected_replacements: dict[str, tuple[str, str]] = {
        "semantic:dau": (candidate_roots["semantic:dau"], baseline["semantic:dau"].baseline_action),
        "metric:dau": (
            canonical_sha256(
                {
                    "metric": "dau",
                    "producer_surface": candidate_roots["contract:producer_shape"],
                    "semantic_surface": candidate_roots["semantic:dau"],
                }
            ),
            baseline["metric:dau"].baseline_action,
        ),
    }
    for row in recomputed.to_dict(orient="records"):
        metric = str(row["metric"])
        product = metric.split(":", 1)[0]
        approved = bool(row["approved"])
        forecast_action = "APPROVE" if approved else "WITHHOLD"
        expected_replacements[f"forecast:{metric}"] = (canonical_sha256(row), forecast_action)
        expected_replacements[f"planning:{metric}"] = (
            canonical_sha256(
                {
                    "product": product,
                    "metric": "dau",
                    "forecast_action": forecast_action,
                }
            ),
            "PLAN" if approved else "WITHHOLD",
        )

    if set(expected_replacements) != AFFECTED_DAU_NODES:
        raise AssertionError("Independent replacement set mismatch")
    for node_id, node in stored_graph.items():
        if node_id not in AFFECTED_DAU_NODES:
            if node != baseline[node_id]:
                raise AssertionError(f"Unaffected node changed during revalidation: {node_id}")
        else:
            expected_fingerprint, expected_action = expected_replacements[node_id]
            if node.fingerprint != expected_fingerprint:
                raise AssertionError(f"Revalidated fingerprint mismatch: {node_id}")
            if node.baseline_action != expected_action:
                raise AssertionError(f"Revalidated action mismatch: {node_id}")
            if node.dependencies != baseline[node_id].dependencies or node.kind != baseline[node_id].kind:
                raise AssertionError(f"Revalidation changed lineage structure for {node_id}")

    if any(stored_graph[node_id] != baseline[node_id] for node_id in PRICING_CHAIN):
        raise AssertionError("Pricing chain was changed by DAU-only revalidation")
    final = propagate_invalidation(stored_graph_nodes, candidate_roots)
    final_stale = [record.node_id for record in final if record.status != FRESH]
    if final_stale:
        raise AssertionError(f"Revalidated graph still stale: {final_stale}")

    scenario_evidence = evidence["scenarios"]["semantic_explicit_versioned_adoption"]
    if set(scenario_evidence["replacement_fingerprints"]) != AFFECTED_DAU_NODES:
        raise AssertionError("Stored replacement fingerprint set mismatch")
    if scenario_evidence["original_migration_action"] != "WITHHOLD":
        raise AssertionError("Revalidation evidence overwrote original migration action")

    print(
        "Evidence revalidation validation passed: additive NOOP; semantic silent replacement blocked; "
        f"explicit semantic adoption revalidated {len(AFFECTED_DAU_NODES)} nodes and reused "
        f"{len(baseline_nodes) - len(AFFECTED_DAU_NODES)}; producer break remains blocked"
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Independently validate v0.42 selective evidence revalidation"
    )
    parser.add_argument("--base-dir", default="build/reference")
    parser.add_argument("--output-dir", default="build/evidence-revalidation")
    args = parser.parse_args()
    validate(Path(args.base_dir), Path(args.output_dir))


if __name__ == "__main__":
    main()
