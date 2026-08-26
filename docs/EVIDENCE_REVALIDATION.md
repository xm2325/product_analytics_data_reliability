# Selective evidence revalidation

v0.42 closes the governance loop introduced by v0.41. Detecting that evidence is stale is necessary, but it is not sufficient for an operating decision system: the system also needs an explicit rule for deciding **whether stale evidence may be rebuilt, which nodes must be rebuilt, which nodes must not be touched, and what must remain blocked**.

## Governance distinction: silent replacement is not adoption

The frozen v0.35 migration decision for broadening DAU from `app_open` to any certified event remains **WITHHOLD**. The candidate changed portfolio DAU by more than the pre-specified 1% compatibility tolerance, so it cannot silently replace the existing KPI.

v0.42 does not relax that tolerance and does not reinterpret the old decision. Instead it models a different event: an explicit, versioned decision to adopt a new DAU definition. Only after that explicit adoption may evidence be rebuilt under the new semantic baseline.

The distinction is therefore:

```text
candidate semantic change
        ↓
old definition silently replaced?
        ├─ yes → WITHHOLD remains binding
        └─ no, explicit versioned adoption
                    ↓
              selective revalidation
```

## Revalidation state machine

The planner has five operational states:

- `NOOP` — no governed fingerprint changed, so all evidence is reused;
- `BLOCKED_EXPLICIT_ADOPTION_REQUIRED` — a semantic migration was withheld as a silent replacement and has not been explicitly adopted;
- `BLOCKED_PRODUCER_INCOMPATIBLE` — producer obligations changed, so downstream recomputation cannot repair the incompatibility;
- `READY` — the change is governable and the exact stale rebuild set is known;
- `REVALIDATED` — every planned stale node has replacement evidence and the new graph is fully fresh.

A `READY` plan is all-or-nothing. `apply_revalidation` requires replacement fingerprints for every planned stale node. A partial rebuild is rejected rather than leaving a graph that appears usable while still depending on stale evidence.

## Controlled scenarios

The reference reuses the same v0.35 migration proposals used by v0.41.

| Scenario | Initial stale | Revalidated | Exact reused | Final stale | Result |
|---|---:|---:|---:|---:|---|
| optional `country` | 0 | 0 | 16 | 0 | `NOOP` |
| DAU silent replacement | 8 | 0 | 8 | 8 | blocked |
| explicit versioned DAU adoption | 8 | 8 | 8 | 0 | `REVALIDATED` |
| required `event_id → event_uuid` producer break | 13 | 0 | 3 | 13 | blocked |

The explicit semantic-adoption path is the positive recovery case:

```text
semantic:dau                 adopt new governed root
    ↓
metric:dau                   recompute candidate metric evidence
    ↓
3 DAU forecasts              rerun leakage-safe rolling-origin evidence
    ↓
3 DAU planning decisions     rebuild actions from the new forecast evidence
```

The deterministic work ledger records:

- **450** Gold product-day metric rows recomputed;
- **3** DAU forecast series recomputed;
- **3** DAU planning decisions recomputed;
- **0** pricing-chain nodes recomputed;
- **8** affected DAG nodes revalidated;
- **8** unaffected DAG nodes reused exactly;
- **16 / 16** nodes fresh after independent verification.

The eight exact-reuse nodes include producer shape, revenue and paid-subscription semantic/metric evidence, the pricing experiment, pricing impact and rollout authorisation. A DAU-only change therefore does not create unnecessary work or silently rewrite unrelated business conclusions.

## Forecast evidence is actually recomputed

The recovery evidence is not a synthetic fingerprint substitution. The v0.42 builder takes the frozen controlled Gold layer, adopts `dau_legacy_any_event` as the explicit candidate DAU series, and reruns the existing leakage-safe forecast contract for all three products.

The independently reconstructed candidate results agree with the separately validated v0.35 migration replay:

| Product | Candidate WAPE | Candidate benchmark WAPE | Coverage | New forecast action |
|---|---:|---:|---:|---|
| `file_transfer` | 5.53% | 7.58% | 100% | `APPROVE` |
| `notes_app` | 4.06% | 4.51% | 100% | `APPROVE` |
| `photo_editor` | 3.77% | 2.46% | 100% | `WITHHOLD` |

The `photo_editor` result remains a useful non-compensatory example: the absolute error is low, but the trivial last-value benchmark is still better, so the planning action remains withheld after the semantic adoption.

## Why the producer break remains blocked

Renaming a required producer field from `event_id` to `event_uuid` changes the producer-shape fingerprint and makes 13 dependent nodes stale. v0.42 deliberately does not claim that downstream recomputation can repair this case.

The required next step would be a compatible producer or a separately governed adapter. Until that exists, the plan remains `BLOCKED_PRODUCER_INCOMPATIBLE` with 13 stale nodes. This prevents a downstream rebuild from masking an unresolved ingestion contract break.

## Independent validation

`scripts/validate_evidence_revalidation_reference.py` does not import the production revalidation planner.

It independently:

- reconstructs the four scenario expectations;
- rebuilds the candidate DAU forecast evidence from Gold and Silver;
- cross-checks candidate forecast WAPE, benchmark WAPE, interval coverage and approval against the frozen v0.35 migration evidence;
- reconstructs the original 16-node graph and the eight-node DAU stale set;
- reconstructs the expected replacement fingerprints and actions;
- verifies every unaffected node is exactly unchanged;
- verifies the pricing experiment/impact/authorisation chain is not recomputed;
- re-runs invalidation against the new graph and requires **zero remaining stale nodes**.

## Claim boundary

v0.42 is deterministic controlled evidence for selective revalidation on a declared dependency graph. It is not a production lineage scheduler, workflow engine, distributed build system or runtime capacity benchmark.

The work figures above are deterministic row/series/decision counts. No latency, QPS or speedup claim is inferred from shared GitHub runners.
