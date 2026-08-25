# Selective downstream evidence invalidation

v0.41 adds a controlled dependency-governance layer over the frozen v0.35 decision evidence. The problem is different from detecting a schema or metric change: once a governed input changes, the system must know **which existing forecasts, plans and decisions are no longer supported by the evidence they were built from**.

## Design goal

A downstream result is not considered fresh merely because its numeric output is unchanged. It is fresh only when:

1. its own governed fingerprint is unchanged; and
2. every dependency it was built from remains fresh.

Stale evidence fails closed as `WITHHOLD_STALE`. This is separate from the original business action. For example, the pricing experiment remains a baseline `HOLD`; a DAU-only semantic change must not rewrite that business conclusion because the pricing chain does not depend on DAU.

## Why scoped fingerprints instead of one global contract hash?

Hashing the entire event contract would over-invalidate. Adding an optional, unused `country` dimension changes the raw contract JSON but does not change the producer obligations or metric semantics used by the existing evidence.

v0.41 therefore fingerprints governed dependency surfaces:

- `contract:producer_shape`: grain, required columns and processing-time obligations;
- `semantic:dau`: activity event and active-use rule;
- `semantic:revenue_gbp`: revenue value and scope rules;
- `semantic:paid_subscription`: subscription-event semantic surface.

This allows a compatible additive change to remain fresh while still failing closed for a required-column break or a KPI semantic change.

## Reference dependency graph

The controlled reference has 16 nodes:

```text
contract:producer_shape
  ├─ metric:dau ────────────────┬─ forecast:file_transfer:dau ── planning:file_transfer:dau
  │                             ├─ forecast:notes_app:dau ───── planning:notes_app:dau
  │                             └─ forecast:photo_editor:dau ── planning:photo_editor:dau
  ├─ metric:revenue_gbp ────────┐
  └─ metric:paid_subscription ───┴─ experiment:pricing ── impact:pricing ── authorisation:pricing

semantic:dau ──────────────────────┘ metric:dau
semantic:revenue_gbp ──────────────┘ metric:revenue_gbp
semantic:paid_subscription ────────┘ metric:paid_subscription
```

The graph preserves baseline decision actions (`APPROVE`, `WITHHOLD`, `HOLD`, `COUNTERFACTUAL_ONLY`) separately from evidence freshness.

## Three controlled change scenarios

The scenarios reuse the already-governed v0.35 migration proposals rather than inventing new post-hoc examples.

| Proposal | Migration action | Fresh | Direct stale | Downstream stale | Total stale | Pricing chain fresh |
|---|---|---:|---:|---:|---:|---|
| add optional `country` | APPROVE | 16 | 0 | 0 | 0 | yes |
| broaden DAU to any certified event | WITHHOLD | 8 | 1 | 7 | 8 | yes |
| rename required `event_id` → `event_uuid` | WITHHOLD | 3 | 1 | 12 | 13 | no |

### Additive optional field

The optional `country` proposal changes the full contract document but not any governed producer or metric-semantic fingerprint used by the evidence graph. All 16 nodes stay fresh. This guards against noisy false-positive invalidation.

### DAU semantic change

Broadening DAU from `app_open` to any certified event directly changes `semantic:dau`. That makes `metric:dau`, all three DAU forecast records and all three DAU planning decisions stale: **8 stale nodes in total**.

The pricing experiment, pricing impact scenario and rollout authorisation remain fresh because they depend on revenue and paid-subscription semantics, not DAU. Their baseline actions remain `HOLD`, `COUNTERFACTUAL_ONLY` and `WITHHOLD` respectively.

This strengthens the earlier v0.35 result. v0.35 showed that forecast eligibility happened to remain unchanged under the candidate DAU definition. v0.41 makes the governance rule explicit: **unchanged forecast eligibility cannot make an old forecast evidence record fresh when the KPI semantics it was built on changed**.

### Required producer break

Renaming required `event_id` to `event_uuid` changes the producer-shape fingerprint. All certified metrics depending on that producer surface become stale; stale metrics then propagate to DAU forecasts/plans and to the pricing experiment/impact/authorisation chain. Only the three independent metric-semantic roots remain fresh.

## Independent validation

`scripts/validate_evidence_invalidation_reference.py` does not import `product_analytics.evidence_invalidation`.

It independently:

- reconstructs the 16-node DAG from the frozen base evidence;
- recomputes canonical SHA-256 fingerprints;
- topologically propagates direct and downstream staleness;
- checks every generated scenario row;
- checks exact scenario counts;
- verifies that the DAU-only semantic change does not falsely invalidate the unrelated pricing chain.

The production implementation also rejects unknown dependencies and cycles, covered by unit tests.

## Evidence files

The v0.41 controlled lane produces:

- `evidence_dependency_graph.json` — baseline DAG, fingerprints and policy;
- `evidence_invalidation_scenarios.csv` — node-level result for every migration scenario;
- `evidence_invalidation_summary.csv` — scenario-level counts and stale-node sets;
- `evidence_invalidation_evidence.json` — compact scenario evidence.

These are uploaded with the controlled GitHub Actions evidence bundle but deliberately do not rewrite the historical v0.35 `MANIFEST.json` or its pinned public claim ledger.

## Claim boundary

This is deterministic controlled evidence for **dependency-aware decision invalidation**. It is not a production lineage catalogue, workflow scheduler, distributed cache-invalidation protocol or guarantee that every organisational dependency has been modelled.

The important claim is narrower: given the declared 16-node graph and governed fingerprint surfaces, the repository can distinguish a harmless additive change from a KPI semantic change and from a producer-breaking change, then fail closed only along the affected dependency paths.
