from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
from typing import Any

import pandas as pd


VERSION = "0.41.0"
FRESH = "FRESH"
DIRECT_STALE = "DIRECT_STALE"
DOWNSTREAM_STALE = "DOWNSTREAM_STALE"
PRICING_CHAIN = {"experiment:pricing", "impact:pricing", "authorisation:pricing"}
EXPECTED_COUNTS = {
    "add_optional_country": (16, 0, 0, 0, True),
    "broaden_dau_to_any_event": (8, 1, 7, 8, True),
    "rename_required_event_id": (3, 1, 12, 13, False),
}


def _json_default(value: Any) -> Any:
    if hasattr(value, "item"):
        return value.item()
    if hasattr(value, "isoformat"):
        return value.isoformat()
    raise TypeError(type(value).__name__)


def _hash(payload: Any) -> str:
    raw = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
        default=_json_default,
    ).encode("utf-8")
    return sha256(raw).hexdigest()


def _read_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def _bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"true", "1"}:
        return True
    if text in {"false", "0"}:
        return False
    raise AssertionError(f"invalid boolean: {value!r}")


def _producer(contract: dict[str, Any]) -> dict[str, Any]:
    return {
        "grain": contract.get("grain"),
        "required_columns": sorted(contract.get("required_columns", [])),
        "generated_processing_time_column": contract.get("generated_processing_time_column"),
        "legacy_processing_time_fallback": contract.get("legacy_processing_time_fallback"),
    }


def _semantic(contract: dict[str, Any], metric: str) -> dict[str, Any]:
    rules = dict(contract.get("rules", {}))
    if metric == "dau":
        return {
            "metric": "dau",
            "activity_event": contract.get("activity_event"),
            "active_use_rule": rules.get("active_use"),
        }
    if metric == "revenue_gbp":
        return {
            "metric": "revenue_gbp",
            "revenue_rule": rules.get("revenue_gbp"),
            "revenue_scope_rule": rules.get("revenue_scope"),
        }
    if metric == "paid_subscription":
        return {
            "metric": "paid_subscription",
            "allowed_event_types": sorted(contract.get("allowed_event_types", [])),
            "definition": "daily paid-subscription state derived from certified subscription evidence",
        }
    raise AssertionError(metric)


def _root_hashes(contract: dict[str, Any]) -> dict[str, str]:
    return {
        "contract:producer_shape": _hash(_producer(contract)),
        "semantic:dau": _hash(_semantic(contract, "dau")),
        "semantic:revenue_gbp": _hash(_semantic(contract, "revenue_gbp")),
        "semantic:paid_subscription": _hash(_semantic(contract, "paid_subscription")),
    }


def _expected_nodes(
    contract: dict[str, Any],
    forecast_rows: list[dict[str, Any]],
    experiment: dict[str, Any],
    impact: dict[str, Any],
) -> list[dict[str, Any]]:
    roots = _root_hashes(contract)
    nodes: list[dict[str, Any]] = [
        {
            "node_id": "contract:producer_shape",
            "kind": "contract_surface",
            "dependencies": [],
            "fingerprint": roots["contract:producer_shape"],
            "baseline_action": "CERTIFIED",
        },
        {
            "node_id": "semantic:dau",
            "kind": "metric_semantics",
            "dependencies": [],
            "fingerprint": roots["semantic:dau"],
            "baseline_action": "CERTIFIED",
        },
        {
            "node_id": "semantic:revenue_gbp",
            "kind": "metric_semantics",
            "dependencies": [],
            "fingerprint": roots["semantic:revenue_gbp"],
            "baseline_action": "CERTIFIED",
        },
        {
            "node_id": "semantic:paid_subscription",
            "kind": "metric_semantics",
            "dependencies": [],
            "fingerprint": roots["semantic:paid_subscription"],
            "baseline_action": "CERTIFIED",
        },
    ]
    for metric in ("dau", "revenue_gbp", "paid_subscription"):
        nodes.append(
            {
                "node_id": f"metric:{metric}",
                "kind": "certified_metric",
                "dependencies": ["contract:producer_shape", f"semantic:{metric}"],
                "fingerprint": _hash(
                    {
                        "metric": metric,
                        "producer_surface": roots["contract:producer_shape"],
                        "semantic_surface": roots[f"semantic:{metric}"],
                    }
                ),
                "baseline_action": "CERTIFIED",
            }
        )

    dau = [dict(row) for row in forecast_rows if str(row["metric"]).endswith(":dau")]
    if len(dau) != 3:
        raise AssertionError(f"expected three DAU forecasts, got {len(dau)}")
    for row in sorted(dau, key=lambda item: str(item["metric"])):
        metric_name = str(row["metric"])
        product = metric_name.split(":", 1)[0]
        approved = _bool(row["approved"])
        forecast_id = f"forecast:{metric_name}"
        nodes.append(
            {
                "node_id": forecast_id,
                "kind": "forecast_evidence",
                "dependencies": ["metric:dau"],
                "fingerprint": _hash(row),
                "baseline_action": "APPROVE" if approved else "WITHHOLD",
            }
        )
        nodes.append(
            {
                "node_id": f"planning:{metric_name}",
                "kind": "planning_decision",
                "dependencies": [forecast_id],
                "fingerprint": _hash(
                    {
                        "product": product,
                        "metric": "dau",
                        "forecast_action": "APPROVE" if approved else "WITHHOLD",
                    }
                ),
                "baseline_action": "PLAN" if approved else "WITHHOLD",
            }
        )

    experiment_action = str(experiment["decision"]["action"]).upper()
    nodes.append(
        {
            "node_id": "experiment:pricing",
            "kind": "experiment_decision",
            "dependencies": ["metric:revenue_gbp", "metric:paid_subscription"],
            "fingerprint": _hash(experiment),
            "baseline_action": experiment_action,
        }
    )
    nodes.append(
        {
            "node_id": "impact:pricing",
            "kind": "impact_plan",
            "dependencies": ["experiment:pricing"],
            "fingerprint": _hash(impact),
            "baseline_action": str(impact["planning_status"]).upper(),
        }
    )
    authorised = bool(impact.get("decision_authorised_rollout", False))
    nodes.append(
        {
            "node_id": "authorisation:pricing",
            "kind": "authorisation_decision",
            "dependencies": ["experiment:pricing", "impact:pricing"],
            "fingerprint": _hash(
                {
                    "decision_authorised_rollout": authorised,
                    "authorised_treated_users": impact.get("authorised_treated_users"),
                    "authorised_incremental_revenue_gbp": impact.get(
                        "authorised_incremental_revenue_gbp"
                    ),
                }
            ),
            "baseline_action": "AUTHORISE" if authorised else "WITHHOLD",
        }
    )
    return nodes


def _topological(nodes: list[dict[str, Any]]) -> list[str]:
    by_id = {node["node_id"]: node for node in nodes}
    if len(by_id) != len(nodes):
        raise AssertionError("duplicate node ids")
    state: dict[str, int] = {}
    order: list[str] = []

    def visit(node_id: str) -> None:
        if node_id not in by_id:
            raise AssertionError(f"unknown dependency {node_id}")
        if state.get(node_id) == 1:
            raise AssertionError("cycle in stored dependency graph")
        if state.get(node_id) == 2:
            return
        state[node_id] = 1
        for dep in by_id[node_id]["dependencies"]:
            visit(dep)
        state[node_id] = 2
        order.append(node_id)

    for node in nodes:
        visit(node["node_id"])
    return order


def _propagate(
    nodes: list[dict[str, Any]], candidate_roots: dict[str, str]
) -> list[dict[str, Any]]:
    by_id = {node["node_id"]: node for node in nodes}
    records: dict[str, dict[str, Any]] = {}
    for node_id in _topological(nodes):
        node = by_id[node_id]
        candidate = candidate_roots.get(node_id, node["fingerprint"])
        direct = candidate != node["fingerprint"]
        stale_deps = [dep for dep in node["dependencies"] if records[dep]["status"] != FRESH]
        status = DIRECT_STALE if direct else DOWNSTREAM_STALE if stale_deps else FRESH
        records[node_id] = {
            "node_id": node_id,
            "kind": node["kind"],
            "status": status,
            "baseline_action": node["baseline_action"],
            "effective_action": node["baseline_action"] if status == FRESH else "WITHHOLD_STALE",
            "direct_fingerprint_changed": direct,
            "stale_dependencies": ";".join(stale_deps),
            "baseline_fingerprint": node["fingerprint"],
            "candidate_fingerprint": candidate,
        }
    return list(records.values())


def validate(base_dir: Path, output_dir: Path) -> None:
    graph = _read_json(output_dir / "evidence_dependency_graph.json")
    evidence = _read_json(output_dir / "evidence_invalidation_evidence.json")
    details = pd.read_csv(output_dir / "evidence_invalidation_scenarios.csv", dtype=str, keep_default_na=False)
    summary = pd.read_csv(output_dir / "evidence_invalidation_summary.csv", dtype=str, keep_default_na=False)
    current = _read_json(base_dir / "event_contract.json")
    proposals = _read_json(base_dir / "migration_proposals.json")
    migrations = _read_json(base_dir / "migration_decisions.json")
    experiment = _read_json(base_dir / "pricing_experiment_decision.json")
    impact = _read_json(base_dir / "pricing_impact_decision.json")
    forecasts = pd.read_csv(base_dir / "forecast_evaluations.csv").to_dict(orient="records")

    if not all(isinstance(item, dict) for item in (graph, evidence, current, proposals, migrations, experiment, impact)):
        raise AssertionError("expected JSON objects")
    if graph.get("version") != VERSION or evidence.get("version") != VERSION:
        raise AssertionError("v0.41 evidence version mismatch")

    expected_nodes = _expected_nodes(current, forecasts, experiment, impact)
    if graph.get("nodes") != expected_nodes:
        raise AssertionError("dependency graph does not match independent reconstruction")
    if graph.get("baseline_root_fingerprints") != _root_hashes(current):
        raise AssertionError("baseline root fingerprints changed")

    actions = {str(row["proposal"]): str(row["action"]) for row in migrations["decisions"]}
    if set(actions) != set(proposals):
        raise AssertionError("proposal/action set mismatch")

    for proposal_name in sorted(proposals):
        candidate_roots = _root_hashes(proposals[proposal_name])
        expected = _propagate(expected_nodes, candidate_roots)
        expected_by_id = {row["node_id"]: row for row in expected}
        stored = details.loc[details["proposal"].eq(proposal_name)]
        if len(stored) != len(expected_nodes):
            raise AssertionError(f"{proposal_name}: detail row count mismatch")
        for _, row in stored.iterrows():
            node_id = row["node_id"]
            if node_id not in expected_by_id:
                raise AssertionError(f"{proposal_name}: unexpected node {node_id}")
            wanted = expected_by_id[node_id]
            for field in (
                "kind",
                "status",
                "baseline_action",
                "effective_action",
                "stale_dependencies",
                "baseline_fingerprint",
                "candidate_fingerprint",
            ):
                if str(row[field]) != str(wanted[field]):
                    raise AssertionError(f"{proposal_name}/{node_id}: {field} mismatch")
            if _bool(row["direct_fingerprint_changed"]) != bool(wanted["direct_fingerprint_changed"]):
                raise AssertionError(f"{proposal_name}/{node_id}: direct-change mismatch")
            if row["migration_action"] != actions[proposal_name]:
                raise AssertionError(f"{proposal_name}: migration action mismatch")

        status_counts = {
            FRESH: sum(item["status"] == FRESH for item in expected),
            DIRECT_STALE: sum(item["status"] == DIRECT_STALE for item in expected),
            DOWNSTREAM_STALE: sum(item["status"] == DOWNSTREAM_STALE for item in expected),
        }
        total_stale = status_counts[DIRECT_STALE] + status_counts[DOWNSTREAM_STALE]
        pricing_chain_fresh = all(expected_by_id[node]["status"] == FRESH for node in PRICING_CHAIN)
        expected_count_tuple = (
            status_counts[FRESH],
            status_counts[DIRECT_STALE],
            status_counts[DOWNSTREAM_STALE],
            total_stale,
            pricing_chain_fresh,
        )
        if expected_count_tuple != EXPECTED_COUNTS[proposal_name]:
            raise AssertionError(f"{proposal_name}: unexpected reference count tuple {expected_count_tuple}")

        stored_summary = summary.loc[summary["proposal"].eq(proposal_name)]
        if len(stored_summary) != 1:
            raise AssertionError(f"{proposal_name}: summary row mismatch")
        row = stored_summary.iloc[0]
        if int(row["nodes"]) != 16:
            raise AssertionError(f"{proposal_name}: node count mismatch")
        for field, expected_value in (
            ("fresh", status_counts[FRESH]),
            ("direct_stale", status_counts[DIRECT_STALE]),
            ("downstream_stale", status_counts[DOWNSTREAM_STALE]),
            ("total_stale", total_stale),
        ):
            if int(row[field]) != expected_value:
                raise AssertionError(f"{proposal_name}: {field} mismatch")
        if _bool(row["pricing_chain_fresh"]) != pricing_chain_fresh:
            raise AssertionError(f"{proposal_name}: pricing-chain freshness mismatch")

    semantic = details.loc[details["proposal"].eq("broaden_dau_to_any_event")].set_index("node_id")
    if semantic.loc["semantic:dau", "status"] != DIRECT_STALE:
        raise AssertionError("DAU semantic root must be directly stale")
    for node_id in (
        "metric:dau",
        "forecast:file_transfer:dau",
        "forecast:notes_app:dau",
        "forecast:photo_editor:dau",
        "planning:file_transfer:dau",
        "planning:notes_app:dau",
        "planning:photo_editor:dau",
    ):
        if semantic.loc[node_id, "status"] != DOWNSTREAM_STALE:
            raise AssertionError(f"semantic scenario failed to stale {node_id}")
    for node_id, action in (
        ("experiment:pricing", "HOLD"),
        ("impact:pricing", "COUNTERFACTUAL_ONLY"),
        ("authorisation:pricing", "WITHHOLD"),
    ):
        if semantic.loc[node_id, "status"] != FRESH:
            raise AssertionError(f"unrelated pricing evidence was falsely invalidated: {node_id}")
        if semantic.loc[node_id, "effective_action"] != action:
            raise AssertionError(f"unrelated pricing action changed: {node_id}")

    print(
        "Evidence invalidation validation passed: 16-node DAG; "
        "additive=0 stale, DAU semantic=8 stale, producer breaking=13 stale"
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Independently validate v0.41 selective evidence invalidation"
    )
    parser.add_argument("--base-dir", default="build/reference")
    parser.add_argument("--output-dir", default="build/evidence-invalidation")
    args = parser.parse_args()
    validate(Path(args.base_dir), Path(args.output_dir))


if __name__ == "__main__":
    main()
