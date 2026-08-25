from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import json
from typing import Any, Iterable, Mapping


FRESH = "FRESH"
DIRECT_STALE = "DIRECT_STALE"
DOWNSTREAM_STALE = "DOWNSTREAM_STALE"
STALE_ACTION = "WITHHOLD_STALE"


@dataclass(frozen=True)
class EvidenceNode:
    node_id: str
    kind: str
    dependencies: tuple[str, ...]
    fingerprint: str
    baseline_action: str


@dataclass(frozen=True)
class InvalidationRecord:
    node_id: str
    kind: str
    status: str
    baseline_action: str
    effective_action: str
    direct_fingerprint_changed: bool
    stale_dependencies: tuple[str, ...]
    baseline_fingerprint: str
    candidate_fingerprint: str


def _json_default(value: Any) -> Any:
    if hasattr(value, "item"):
        return value.item()
    if hasattr(value, "isoformat"):
        return value.isoformat()
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serialisable")


def canonical_sha256(payload: Any) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
        default=_json_default,
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


def producer_shape_projection(contract: Mapping[str, Any]) -> dict[str, Any]:
    """Project producer obligations that can invalidate all certified downstream data.

    Optional dimensions are intentionally excluded. Adding an unused optional field
    must not stale evidence whose producer obligations and metric semantics did not
    change.
    """
    return {
        "grain": contract.get("grain"),
        "required_columns": sorted(contract.get("required_columns", [])),
        "generated_processing_time_column": contract.get("generated_processing_time_column"),
        "legacy_processing_time_fallback": contract.get("legacy_processing_time_fallback"),
    }


def metric_semantics_projection(contract: Mapping[str, Any], metric: str) -> dict[str, Any]:
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
    raise ValueError(f"Unsupported governed metric: {metric}")


def root_fingerprints(contract: Mapping[str, Any]) -> dict[str, str]:
    return {
        "contract:producer_shape": canonical_sha256(producer_shape_projection(contract)),
        "semantic:dau": canonical_sha256(metric_semantics_projection(contract, "dau")),
        "semantic:revenue_gbp": canonical_sha256(
            metric_semantics_projection(contract, "revenue_gbp")
        ),
        "semantic:paid_subscription": canonical_sha256(
            metric_semantics_projection(contract, "paid_subscription")
        ),
    }


def _normalise_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"true", "1"}:
        return True
    if text in {"false", "0"}:
        return False
    raise ValueError(f"Cannot interpret boolean value: {value!r}")


def build_reference_graph(
    *,
    event_contract_payload: Mapping[str, Any],
    forecast_rows: Iterable[Mapping[str, Any]],
    experiment_payload: Mapping[str, Any],
    impact_payload: Mapping[str, Any],
) -> tuple[EvidenceNode, ...]:
    roots = root_fingerprints(event_contract_payload)
    nodes: list[EvidenceNode] = [
        EvidenceNode(
            node_id="contract:producer_shape",
            kind="contract_surface",
            dependencies=(),
            fingerprint=roots["contract:producer_shape"],
            baseline_action="CERTIFIED",
        ),
        EvidenceNode(
            node_id="semantic:dau",
            kind="metric_semantics",
            dependencies=(),
            fingerprint=roots["semantic:dau"],
            baseline_action="CERTIFIED",
        ),
        EvidenceNode(
            node_id="semantic:revenue_gbp",
            kind="metric_semantics",
            dependencies=(),
            fingerprint=roots["semantic:revenue_gbp"],
            baseline_action="CERTIFIED",
        ),
        EvidenceNode(
            node_id="semantic:paid_subscription",
            kind="metric_semantics",
            dependencies=(),
            fingerprint=roots["semantic:paid_subscription"],
            baseline_action="CERTIFIED",
        ),
    ]

    for metric in ("dau", "revenue_gbp", "paid_subscription"):
        nodes.append(
            EvidenceNode(
                node_id=f"metric:{metric}",
                kind="certified_metric",
                dependencies=("contract:producer_shape", f"semantic:{metric}"),
                fingerprint=canonical_sha256(
                    {
                        "metric": metric,
                        "producer_surface": roots["contract:producer_shape"],
                        "semantic_surface": roots[f"semantic:{metric}"],
                    }
                ),
                baseline_action="CERTIFIED",
            )
        )

    dau_rows = [dict(row) for row in forecast_rows if str(row.get("metric", "")).endswith(":dau")]
    if len(dau_rows) != 3:
        raise ValueError(f"Expected exactly three controlled DAU forecast rows, got {len(dau_rows)}")

    for row in sorted(dau_rows, key=lambda item: str(item["metric"])):
        metric_name = str(row["metric"])
        product = metric_name.split(":", 1)[0]
        approved = _normalise_bool(row.get("approved"))
        forecast_node = f"forecast:{metric_name}"
        nodes.append(
            EvidenceNode(
                node_id=forecast_node,
                kind="forecast_evidence",
                dependencies=("metric:dau",),
                fingerprint=canonical_sha256(row),
                baseline_action="APPROVE" if approved else "WITHHOLD",
            )
        )
        nodes.append(
            EvidenceNode(
                node_id=f"planning:{metric_name}",
                kind="planning_decision",
                dependencies=(forecast_node,),
                fingerprint=canonical_sha256(
                    {
                        "product": product,
                        "metric": "dau",
                        "forecast_action": "APPROVE" if approved else "WITHHOLD",
                    }
                ),
                baseline_action="PLAN" if approved else "WITHHOLD",
            )
        )

    decision = dict(experiment_payload.get("decision", {}))
    experiment_action = str(decision.get("action", "")).upper()
    if not experiment_action:
        raise ValueError("pricing experiment decision action is missing")
    nodes.append(
        EvidenceNode(
            node_id="experiment:pricing",
            kind="experiment_decision",
            dependencies=("metric:revenue_gbp", "metric:paid_subscription"),
            fingerprint=canonical_sha256(experiment_payload),
            baseline_action=experiment_action,
        )
    )

    planning_status = str(impact_payload.get("planning_status", "")).upper()
    if not planning_status:
        raise ValueError("pricing impact planning status is missing")
    nodes.append(
        EvidenceNode(
            node_id="impact:pricing",
            kind="impact_plan",
            dependencies=("experiment:pricing",),
            fingerprint=canonical_sha256(impact_payload),
            baseline_action=planning_status,
        )
    )

    authorised = bool(impact_payload.get("decision_authorised_rollout", False))
    nodes.append(
        EvidenceNode(
            node_id="authorisation:pricing",
            kind="authorisation_decision",
            dependencies=("experiment:pricing", "impact:pricing"),
            fingerprint=canonical_sha256(
                {
                    "decision_authorised_rollout": authorised,
                    "authorised_treated_users": impact_payload.get("authorised_treated_users"),
                    "authorised_incremental_revenue_gbp": impact_payload.get(
                        "authorised_incremental_revenue_gbp"
                    ),
                }
            ),
            baseline_action="AUTHORISE" if authorised else "WITHHOLD",
        )
    )

    validate_graph(nodes)
    return tuple(nodes)


def validate_graph(nodes: Iterable[EvidenceNode]) -> tuple[str, ...]:
    materialised = tuple(nodes)
    ids = [node.node_id for node in materialised]
    if len(ids) != len(set(ids)):
        raise ValueError("Evidence graph contains duplicate node ids")
    by_id = {node.node_id: node for node in materialised}
    for node in materialised:
        unknown = sorted(set(node.dependencies) - set(by_id))
        if unknown:
            raise ValueError(f"{node.node_id} has unknown dependencies: {unknown}")
        if node.node_id in node.dependencies:
            raise ValueError(f"{node.node_id} cannot depend on itself")

    state: dict[str, int] = {}
    order: list[str] = []

    def visit(node_id: str) -> None:
        marker = state.get(node_id, 0)
        if marker == 1:
            raise ValueError(f"Evidence graph contains a cycle at {node_id}")
        if marker == 2:
            return
        state[node_id] = 1
        for dependency in by_id[node_id].dependencies:
            visit(dependency)
        state[node_id] = 2
        order.append(node_id)

    for node_id in ids:
        visit(node_id)
    return tuple(order)


def propagate_invalidation(
    nodes: Iterable[EvidenceNode],
    candidate_fingerprints: Mapping[str, str],
) -> tuple[InvalidationRecord, ...]:
    materialised = tuple(nodes)
    order = validate_graph(materialised)
    by_id = {node.node_id: node for node in materialised}
    unknown_candidates = sorted(set(candidate_fingerprints) - set(by_id))
    if unknown_candidates:
        raise ValueError(f"Candidate fingerprints contain unknown nodes: {unknown_candidates}")

    records: dict[str, InvalidationRecord] = {}
    for node_id in order:
        node = by_id[node_id]
        candidate = str(candidate_fingerprints.get(node_id, node.fingerprint))
        direct_changed = candidate != node.fingerprint
        stale_dependencies = tuple(
            dependency for dependency in node.dependencies if records[dependency].status != FRESH
        )
        if direct_changed:
            status = DIRECT_STALE
        elif stale_dependencies:
            status = DOWNSTREAM_STALE
        else:
            status = FRESH
        records[node_id] = InvalidationRecord(
            node_id=node.node_id,
            kind=node.kind,
            status=status,
            baseline_action=node.baseline_action,
            effective_action=node.baseline_action if status == FRESH else STALE_ACTION,
            direct_fingerprint_changed=direct_changed,
            stale_dependencies=stale_dependencies,
            baseline_fingerprint=node.fingerprint,
            candidate_fingerprint=candidate,
        )
    return tuple(records[node_id] for node_id in order)


def summarise_invalidation(records: Iterable[InvalidationRecord]) -> dict[str, Any]:
    materialised = tuple(records)
    stale_ids = sorted(record.node_id for record in materialised if record.status != FRESH)
    return {
        "nodes": len(materialised),
        "fresh": sum(record.status == FRESH for record in materialised),
        "direct_stale": sum(record.status == DIRECT_STALE for record in materialised),
        "downstream_stale": sum(record.status == DOWNSTREAM_STALE for record in materialised),
        "total_stale": len(stale_ids),
        "stale_node_ids": stale_ids,
    }


def serialise_graph(nodes: Iterable[EvidenceNode]) -> list[dict[str, Any]]:
    return [asdict(node) for node in nodes]
