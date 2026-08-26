from __future__ import annotations

import pytest

from product_analytics.contracts import event_contract
from product_analytics.evidence_invalidation import (
    EvidenceNode,
    build_reference_graph,
    canonical_sha256,
    propagate_invalidation,
    root_fingerprints,
)
from product_analytics.evidence_revalidation import (
    BLOCKED_EXPLICIT_ADOPTION_REQUIRED,
    BLOCKED_PRODUCER_INCOMPATIBLE,
    NOOP,
    READY,
    apply_revalidation,
    plan_revalidation,
    verify_revalidated_freshness,
)
from product_analytics.migration_governance import (
    classify_event_contract_change,
    migration_proposals,
)


def _graph():
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


def _plan(proposal_name: str, *, migration_action: str, explicit: bool = False):
    nodes = _graph()
    proposal = migration_proposals()[proposal_name]
    classification = classify_event_contract_change(event_contract(), proposal)
    records = propagate_invalidation(nodes, root_fingerprints(proposal))
    return nodes, proposal, plan_revalidation(
        proposal=proposal_name,
        classification=classification.classification,
        migration_action=migration_action,
        invalidation_records=records,
        explicit_semantic_adoption=explicit,
    )


def test_additive_change_is_noop_and_reuses_all_nodes():
    nodes, _, plan = _plan("add_optional_country", migration_action="APPROVE")
    assert plan.status == NOOP
    assert plan.rebuild_node_ids == ()
    assert len(plan.reused_node_ids) == 16
    assert apply_revalidation(
        baseline_nodes=nodes,
        plan=plan,
        replacement_fingerprints={},
        replacement_actions={},
    ) == nodes


def test_silent_semantic_replacement_remains_blocked():
    _, _, plan = _plan("broaden_dau_to_any_event", migration_action="WITHHOLD")
    assert plan.status == BLOCKED_EXPLICIT_ADOPTION_REQUIRED
    assert len(plan.initial_stale_node_ids) == 8
    assert plan.rebuild_node_ids == ()


def test_explicit_semantic_adoption_plans_only_eight_stale_nodes():
    _, _, plan = _plan(
        "broaden_dau_to_any_event",
        migration_action="WITHHOLD",
        explicit=True,
    )
    assert plan.status == READY
    assert len(plan.rebuild_node_ids) == 8
    assert len(plan.reused_node_ids) == 8
    assert plan.rebuild_node_ids[0] == "semantic:dau"
    assert "experiment:pricing" in plan.reused_node_ids
    assert "impact:pricing" in plan.reused_node_ids
    assert "authorisation:pricing" in plan.reused_node_ids


def test_breaking_producer_change_cannot_be_revalidated_downstream():
    _, _, plan = _plan("rename_required_event_id", migration_action="WITHHOLD", explicit=True)
    assert plan.status == BLOCKED_PRODUCER_INCOMPATIBLE
    assert len(plan.initial_stale_node_ids) == 13
    assert plan.rebuild_node_ids == ()


def test_explicit_semantic_revalidation_restores_freshness_and_preserves_unaffected_nodes():
    nodes, proposal, plan = _plan(
        "broaden_dau_to_any_event",
        migration_action="WITHHOLD",
        explicit=True,
    )
    roots = root_fingerprints(proposal)
    baseline = {node.node_id: node for node in nodes}
    replacements: dict[str, str] = {}
    actions: dict[str, str] = {}

    for node_id in plan.rebuild_node_ids:
        if node_id == "semantic:dau":
            replacements[node_id] = roots[node_id]
        elif node_id == "metric:dau":
            replacements[node_id] = canonical_sha256(
                {
                    "metric": "dau",
                    "producer_surface": roots["contract:producer_shape"],
                    "semantic_surface": roots["semantic:dau"],
                }
            )
        elif node_id.startswith("forecast:"):
            replacements[node_id] = canonical_sha256({"rebuilt": node_id, "candidate": "v2"})
            actions[node_id] = baseline[node_id].baseline_action
        elif node_id.startswith("planning:"):
            forecast_id = node_id.replace("planning:", "forecast:", 1)
            replacements[node_id] = canonical_sha256(
                {"rebuilt": node_id, "forecast_fingerprint": replacements[forecast_id]}
            )
            actions[node_id] = baseline[node_id].baseline_action
        else:
            raise AssertionError(node_id)

    updated = apply_revalidation(
        baseline_nodes=nodes,
        plan=plan,
        replacement_fingerprints=replacements,
        replacement_actions=actions,
    )
    verify_revalidated_freshness(
        revalidated_nodes=updated,
        candidate_root_fingerprints=roots,
    )
    updated_by_id = {node.node_id: node for node in updated}
    for node_id in plan.reused_node_ids:
        assert updated_by_id[node_id] == baseline[node_id]

    with pytest.raises(ValueError, match="Replacement fingerprint set mismatch"):
        apply_revalidation(
            baseline_nodes=nodes,
            plan=plan,
            replacement_fingerprints={"semantic:dau": roots["semantic:dau"]},
            replacement_actions={},
        )
