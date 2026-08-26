# Changelog

## v0.43.0

- added a controlled **schema-valid source incident** in which 5,543 `notes_app` `app_open` events from 2026-04-10 through 2026-04-16 are factually misrouted to `file_transfer` while still passing ordinary row-level quality checks with 0 rejects;
- introduced an `event_id`-keyed correction ledger that fails closed on duplicate/unknown IDs or stale incident-state mismatches instead of silently rewriting history;
- derived the exact downstream scope as **2 products × 7 dates = 14 Gold product-days**, then recomputed only **14 / 450** Gold rows while reusing **436 / 450**, a deterministic **96.89% Gold-row recomputation reduction** rather than a latency/speedup claim;
- replayed only **2 affected DAU forecast series** while reusing the unaffected `photo_editor` forecast evidence;
- required corrected Silver to equal clean source Silver exactly, selective Gold repair to equal a clean full Gold rebuild exactly including final dtypes, and selective forecast replay to equal clean full forecast evidence exactly;
- preserved historical decision lineage: **2 published planning decisions are SUPERSEDED**, both have an action change after correction, and the unaffected `photo_editor:dau` decision remains `ACTIVE_UNCHANGED`;
- added an independent validator that does not import `product_analytics.incident_recovery` and independently reconstructs the incident, correction, Gold scope, selective replay, forecasting evidence, decision supersession and evidence hashes;
- kept the historical CSV decimal round-trip boundary separate from core parity: only that text-serialisation comparison permits `1e-12` absolute tolerance; targeted replay versus clean in-memory rebuild remains exact;
- added six focused tests and advanced the full repository suite from **111 to 117 tests**;
- retained all existing controlled, external UCI, incremental recovery, reporting, consumer-contract and concurrent-workload gates;
- advanced repository/package metadata to **0.43.0** while leaving the frozen v0.35 controlled reference, reporting data-product version **0.40.0**, and response schemas **1.0 / 1.1** unchanged.

See [`docs/INCIDENT_RECOVERY.md`](docs/INCIDENT_RECOVERY.md) for the full v0.43 recovery contract and evidence boundary.

## Earlier releases

The complete pre-v0.43 changelog is preserved verbatim in [`CHANGELOG_HISTORY.md`](CHANGELOG_HISTORY.md).
