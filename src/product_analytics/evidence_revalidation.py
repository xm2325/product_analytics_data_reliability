from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Iterable, Mapping

from .evidence_invalidation import (
    FRESH,
    EvidenceNode,
    InvalidationRecord,
    propagate_invalidation,
    validate_graph,
)


NOOP = "NOOP"
READY = "READY"
BLOCKED_EXPLICIT_ADOPTION_REQUIRED = "BLOCKED_EXPLICIT_ADOPTION_REQUIRED"
BLOCKED_PRODUCER_INCOMPATIBLE = "BLOCKED_PRODUCER_INCOMPATIBLE"
REVALIDATED = "REVALIDATED"


@dataclass(frozen=True)
class RevalidationStep:
    node_id: str
    step_type: str
    reason: str


@dataclass(frozen=True)
class RevalidationPlan:
    proposal: str
    classification: str
    migration_action: str
    explicit_semantic_adoption: bool
    status: str
    initial_stale_node_ids: tuple[str, ...]
    steps: tuple[RevalidationStep, ...]
    reused_node_ids: tuple[str, ...]
    blocked_reason: str | None

    @property
    def rebuild_node_ids(self) -> tuple[str, ...]:
        return tuple(step.node_id for step in self.steps)


def plan_revalidation(
    *,
    proposal: str,
    classification: str,
    migration_action: str,
    invalidation_records: Iterable[InvalidationRecord],
    explicit_semantic_adoption: bool = False,
) -> RevalidationPlan:
    """Plan the smallest governed revalidation set for one candidate change.

    The planner never converts a withheld silent semantic replacement into an
    approved migration. A semantic definition can only become the new governed
    baseline after an explicit adoption decision, after which every stale node
    on that dependency path must be rebuilt before reuse.
    """
    records = tuple(invalidation_records)
    stale = tuple(sorted(record.node_id for record in records if record.status != FRESH))
    reused = tuple(sorted(record.node_id for record in records if record.status == FRESH))

    if not stale:
        return RevalidationPlan(
            proposal=proposal,
            classification=classification,
            migration_action=migration_action,
            explicit_semantic_adoption=explicit_semantic_adoption,
            status=NOOP,
            initial_stale_node_ids=(),
            steps=(),
            reused_node_ids=reused,
            blocked_reason=None,
        )

    if classification == "BREAKING":
        return RevalidationPlan(
            proposal=proposal,
            classification=classification,
            migration_action=migration_action,
            explicit_semantic_adoption=explicit_semantic_adoption,
            status=BLOCKED_PRODUCER_INCOMPATIBLE,
            initial_stale_node_ids=stale,
            steps=(),
            reused_node_ids=reused,
            blocked_reason=(
                "producer obligations changed; downstream evidence cannot be revalidated "
                "until a compatible producer or governed adapter exists"
            ),
        )

    if classification == "SEMANTIC" and migration_action != "APPROVE" and not explicit_semantic_adoption:
        return RevalidationPlan(
            proposal=proposal,
            classification=classification,
            migration_action=migration_action,
            explicit_semantic_adoption=False,
            status=BLOCKED_EXPLICIT_ADOPTION_REQUIRED,
            initial_stale_node_ids=stale,
            steps=(),
            reused_node_ids=reused,
            blocked_reason=(
                "silent semantic replacement remains withheld; an explicit versioned semantic "
                "adoption is required before rebuilding evidence under the new definition"
            ),
        )

    by_id = {record.node_id: record for record in records}
    steps: list[RevalidationStep] = []
    for node_id in validate_graph(
        EvidenceNode(
            node_id=record.node_id,
            kind=record.kind,
            dependencies=record.stale_dependencies,
            fingerprint=record.baseline_fingerprint,
            baseline_action=record.baseline_action,
        )
        for record in records
    ):
        if node_id not in stale:
            continue
        record = by_id[node_id]
        step_type = "ADOPT_GOVERNED_ROOT" if record.direct_fingerprint_changed else "REBUILD_EVIDENCE"
        reason = (
            "candidate governed fingerprint becomes the new explicit baseline"
            if record.direct_fingerprint_changed
            else "dependency evidence is stale and must be recomputed before reuse"
        )
        steps.append(RevalidationStep(node_id=node_id, step_type=step_type, reason=reason))

    # validate_graph above uses stale_dependencies rather than the full graph only to
    # ensure a deterministic dependency-respecting order among stale nodes. Roots
    # appear before the descendants that name them as stale dependencies.
    return RevalidationPlan(
        proposal=proposal,
        classification=classification,
        migration_action=migration_action,
        explicit_semantic_adoption=explicit_semantic_adoption,
        status=READY,
        initial_stale_node_ids=stale,
        steps=tuple(steps),
        reused_node_ids=reused,
        blocked_reason=None,
    )


def apply_revalidation(
    *,
    baseline_nodes: Iterable[EvidenceNode],
    plan: RevalidationPlan,
    replacement_fingerprints: Mapping[str, str],
    replacement_actions: Mapping[str, str],
) -> tuple[EvidenceNode, ...]:
    """Create a new governed graph only when every stale node has been rebuilt.

    Unaffected nodes are copied byte-for-byte at the model level: node id, kind,
    dependencies, fingerprint and baseline action all remain unchanged.
    """
    if plan.status == NOOP:
        if replacement_fingerprints or replacement_actions:
            raise ValueError("NOOP revalidation cannot accept replacement evidence")
        nodes = tuple(baseline_nodes)
        validate_graph(nodes)
        return nodes
    if plan.status != READY:
        raise ValueError(f"Cannot apply revalidation plan with status {plan.status}")

    nodes = tuple(baseline_nodes)
    by_id = {node.node_id: node for node in nodes}
    expected = set(plan.rebuild_node_ids)
    if set(replacement_fingerprints) != expected:
        missing = sorted(expected - set(replacement_fingerprints))
        extra = sorted(set(replacement_fingerprints) - expected)
        raise ValueError(f"Replacement fingerprint set mismatch; missing={missing}, extra={extra}")
    unknown_actions = sorted(set(replacement_actions) - expected)
    if unknown_actions:
        raise ValueError(f"Replacement actions contain non-rebuilt nodes: {unknown_actions}")

    updated: list[EvidenceNode] = []
    for node in nodes:
        if node.node_id not in expected:
            updated.append(node)
            continue
        updated.append(
            replace(
                node,
                fingerprint=str(replacement_fingerprints[node.node_id]),
                baseline_action=str(replacement_actions.get(node.node_id, node.baseline_action)),
            )
        )
    validate_graph(updated)
    return tuple(updated)


def verify_revalidated_freshness(
    *,
    revalidated_nodes: Iterable[EvidenceNode],
    candidate_root_fingerprints: Mapping[str, str],
) -> tuple[InvalidationRecord, ...]:
    """Require the adopted candidate roots to be fully fresh in the new graph."""
    records = propagate_invalidation(revalidated_nodes, candidate_root_fingerprints)
    stale = [record.node_id for record in records if record.status != FRESH]
    if stale:
        raise ValueError(f"Revalidated graph still contains stale evidence: {sorted(stale)}")
    return records


def complete_plan(plan: RevalidationPlan) -> RevalidationPlan:
    if plan.status != READY:
        raise ValueError(f"Only READY plans can be completed, got {plan.status}")
    return replace(plan, status=REVALIDATED)
