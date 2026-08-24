# Contract evolution and metric-change governance (v0.35)

A data pipeline can stay technically green while a product metric silently changes meaning. v0.35 treats schema compatibility, metric invariance and downstream decision stability as separate gates.

## Reference migration cases

The reference build evaluates three controlled proposals against the current event contract.

1. **Additive:** add optional `country`. Existing producers remain valid. The shadow replay is required to preserve governed metrics exactly.
2. **Breaking:** rename required `event_id` to `event_uuid`. Existing producers no longer satisfy the required-column contract, so the migration is withheld before downstream metrics are considered.
3. **Semantic:** broaden DAU from unique users with `app_open` to unique users with any certified event. The same certified historical evidence is replayed under both definitions, then the DAU shift and leakage-safe forecast eligibility are recomputed.

The migration rule is deliberately non-compensatory:

```text
existing producers remain compatible
AND governed metric movement <= 1%
AND forecast eligibility is unchanged
=> APPROVE
otherwise => WITHHOLD
```

A small or zero movement in revenue cannot compensate for a material DAU definition change. Likewise, a schema migration cannot be approved merely because downstream code still executes.

## Evidence

The v0.35 reference writes:

- `contract_registry.json` — current contract, candidate contracts and structural classifications;
- `migration_proposals.json` — exact machine-readable proposals;
- `migration_replay.csv` — daily current-vs-candidate DAU plus invariant paid/revenue controls;
- `metric_change_impact.csv` — product-level replay deltas;
- `migration_forecast_impact.csv` — current-vs-candidate leakage-safe DAU forecast evidence;
- `migration_decisions.json` — non-compensatory gate results and final actions.

`validate_contract_migration.py` does not trust the stored decisions. It reloads Gold and Silver evidence, reconstructs the replay, recomputes product-level metric changes, reruns both current and candidate rolling-origin forecasts, reclassifies each proposal, and rebuilds the final migration actions.

## Scope boundary

The study is synthetic and deterministic. The 1% semantic tolerance is a declared reference governance threshold, not a claim about an appropriate production threshold for every product. Real migrations would additionally require product ownership, observability, staged rollout and rollback procedures appropriate to the affected system.
