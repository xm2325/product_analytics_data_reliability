from __future__ import annotations

import pytest

from product_analytics.contracts import event_contract
from product_analytics.evidence_invalidation import (
    DIRECT_STALE,
    DOWNSTREAM_STALE,
    FRESH,
    EvidenceNode,
    build_reference_graph,
    canonical_sha256,
    propagate_invalidation,
    root_fingerprints,
    summarise_invalidation,
    validate_graph,
)
from product_analytics.migration_governance import migration_proposals


def _reference_graph():
    return build_reference_graph(
        event_contract_payload=event_contract(),
        forecast_rows=[
            {"metric": "file_transfer:dau", "approved": True, "wape": 0.05},
            {"metric": "notes_app:dau", "approved": True, "wape": 0.04},
            {"metric": "photo_editor:dau", "approved": False, "wape": 0.039},
        ],
        experiment_payload={"decision": {"action": "hold"}, "integrity": {"passes": True}},
        impact_payload={
            "planning_status": "counterfactual_only",
            "decision_authorised_rollout": False,
            "authorised_treated_users": 0,
            "authorised_incremental_revenue_gbp": None,
        },
    )


def test_additive_optional_dimension_does_not_false_positive_stale_evidence():
    nodes = _reference_graph()
    proposal = migration_proposals()["add_optional_country"]
    records = propagate_invalidation(nodes, root_fingerprints(proposal))
    summary = summarise_invalidation(records)
    assert summary == {
        "nodes": 16,
        "fresh": 16,
        "direct_stale": 0,
        "downstream_stale": 0,
        "total_stale": 0,
        "stale_node_ids": [],
    }


def test_dau_semantic_change_selectively_stales_forecast_and_planning_only():
    nodes = _reference_graph()
    proposal = migration_proposals()["broaden_dau_to_any_event"]
    records = propagate_invalidation(nodes, root_fingerprints(proposal))
    by_id = {record.node_id: record for record in records}
    summary = summarise_invalidation(records)

    assert summary["direct_stale"] == 1
    assert summary["downstream_stale"] == 7
    assert summary["total_stale"] == 8
    assert by_id["semantic:dau"].status == DIRECT_STALE
    assert by_id["metric:dau"].status == DOWNSTREAM_STALE
    for product in ("file_transfer", "notes_app", "photo_editor"):
        assert by_id[f"forecast:{product}:dau"].status == DOWNSTREAM_STALE
        assert by_id[f"planning:{product}:dau"].status == DOWNSTREAM_STALE
    assert by_id["experiment:pricing"].status == FRESH
    assert by_id["experiment:pricing"].effective_action == "HOLD"
    assert by_id["impact:pricing"].status == FRESH
    assert by_id["impact:pricing"].effective_action == "COUNTERFACTUAL_ONLY"
    assert by_id["authorisation:pricing"].status == FRESH
    assert by_id["authorisation:pricing"].effective_action == "WITHHOLD"


def test_breaking_producer_shape_change_stales_every_dependent_decision():
    nodes = _reference_graph()
    proposal = migration_proposals()["rename_required_event_id"]
    records = propagate_invalidation(nodes, root_fingerprints(proposal))
    by_id = {record.node_id: record for record in records}
    summary = summarise_invalidation(records)

    assert summary["fresh"] == 3
    assert summary["direct_stale"] == 1
    assert summary["downstream_stale"] == 12
    assert summary["total_stale"] == 13
    assert by_id["contract:producer_shape"].status == DIRECT_STALE
    for node_id in (
        "metric:dau",
        "metric:revenue_gbp",
        "metric:paid_subscription",
        "experiment:pricing",
        "impact:pricing",
        "authorisation:pricing",
    ):
        assert by_id[node_id].status == DOWNSTREAM_STALE
        assert by_id[node_id].effective_action == "WITHHOLD_STALE"


def test_graph_rejects_unknown_dependency():
    node = EvidenceNode(
        node_id="decision:a",
        kind="decision",
        dependencies=("missing:source",),
        fingerprint=canonical_sha256({"a": 1}),
        baseline_action="APPROVE",
    )
    with pytest.raises(ValueError, match="unknown dependencies"):
        validate_graph([node])


def test_graph_rejects_dependency_cycle():
    nodes = [
        EvidenceNode(
            node_id="a",
            kind="test",
            dependencies=("b",),
            fingerprint=canonical_sha256("a"),
            baseline_action="APPROVE",
        ),
        EvidenceNode(
            node_id="b",
            kind="test",
            dependencies=("a",),
            fingerprint=canonical_sha256("b"),
            baseline_action="APPROVE",
        ),
    ]
    with pytest.raises(ValueError, match="cycle"):
        validate_graph(nodes)
