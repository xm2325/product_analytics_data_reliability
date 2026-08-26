# Incident correction and selective replay — v0.43

v0.43 adds a controlled source-incident recovery path for a failure mode that is different from technical partition corruption (v0.37) and governed semantic adoption (v0.42): source rows can pass the row-level contract, feed downstream evidence, and only later be discovered to be factually wrong.

## Controlled incident

The reference incident relabels every `notes_app` `app_open` event between **2026-04-10 and 2026-04-16** as `file_transfer`. The rows remain schema-valid: event IDs, event types, timestamps and revenue fields are still valid, so ordinary row-level quality rejects **0 rows**.

Validated scope:

| Evidence | Result |
|---|---:|
| Misrouted events | **5,543** |
| Incident days | **7** |
| Affected products | **2** |
| Affected Gold product-days | **14** |
| Total Gold product-days | **450** |
| Gold rows selectively recomputed | **14** |
| Gold rows reused | **436** |
| Deterministic Gold recomputation reduction | **96.89%** |
| Forecast series recomputed | **2** |
| Forecast series reused | **1** |
| Published decisions superseded | **2** |
| Superseded decisions with action change | **2** |
| Unaffected decisions retained | **1** |

The 96.89% figure is deterministic work accounting only. It is not a wall-clock latency, throughput or speedup claim.

## Correction ledger

Corrections are keyed by stable `event_id`. The ledger records the clean/original product, incident product, event type and event date. Application fails closed when the ledger contains duplicate or unknown IDs or when the current incident rows no longer match the declared incident state.

This prevents stale or tampered correction instructions from silently rewriting source history.

## Explicit affected scope

The correction ledger deterministically expands into the downstream scope:

```text
5,543 corrected event IDs
        ↓
2 products × 7 dates
        ↓
14 Gold product-day rows
        ↓
2 DAU forecast series
        ↓
2 published planning decisions
```

`photo_editor` is outside this lineage and its forecast/decision evidence is reused rather than recomputed.

## Exact clean-rebuild parity

The central gate is that a selective repair must produce the same state as rebuilding from the corrected source from scratch:

```text
corrected Silver == clean source Silver                  exact
selectively repaired Gold == clean full Gold rebuild    exact
selectively replayed forecasts == clean full forecasts  exact
```

Gold parity includes keys, values and final dtypes. Partial row stitching is followed by explicit schema restoration so a temporary Pandas nullable/object dtype cannot leak into the repaired result.

The only tolerance is at the historical CSV text-serialisation boundary, where decimal round-tripping can turn a binary float such as `131.89000000000001` into `131.89`. That boundary uses absolute tolerance `1e-12`; targeted replay versus clean in-memory rebuild remains exact.

## Decision supersession

Published decisions are never overwritten. When corrected evidence changes a published forecast, the old record remains with status `SUPERSEDED`, points to one new `ACTIVE` decision, and records reason `SOURCE_DATA_CORRECTION`.

In the controlled reference both affected DAU planning decisions change action after correction, so **2/2** affected published decisions are superseded and replaced. The unaffected `photo_editor:dau` decision remains `ACTIVE_UNCHANGED`.

## Independent validation boundary

`validate_incident_recovery_reference.py` does not import `product_analytics.incident_recovery`. It independently reconstructs:

- the seven-day source incident from the correction ledger;
- row-level quality acceptance;
- the corrected Silver layer;
- Gold aggregation and affected-key scope;
- selective Gold row stitching and clean-rebuild dtype restoration;
- DAU forecast evidence;
- decision supersession cardinality and links;
- deterministic evidence hashes.

The CI gate requires the independent validator to pass after the v0.43 builder.

## Claim boundary

This is controlled recovery evidence, not a claim about a real company incident or a production CDC/lineage platform. It demonstrates stable-identity correction, minimal downstream replay, exact clean-rebuild parity, and auditable supersession in the repository's controlled decision system.