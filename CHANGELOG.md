# Changelog

## v0.24.0

- introduced explicit `app_open` activity events and product-specific decaying return behaviour;
- isolated activity randomness from the commercial RNG so acquisition/trial/paid/purchase reference outcomes remain unchanged;
- migrated current DAU to `unique users with app_open` (metric contract v2.0) while retaining the any-event DAU as `v1.0-deprecated` for dual-run comparison;
- generated daily DAU migration evidence and product-level migration summaries;
- added mature D7/D30 activity-retention cohorts and weighted summaries;
- updated forecasting to consume DAU v2 while preserving the existing observation-maturity cutoff;
- aligned DuckDB SQL Silver/Gold logic with the current Python contracts and added Python↔SQL parity tests;
- expanded reference-build validation to cover activity events, DAU contract versions, migration direction, retention bounds/decay and product activity configuration;
- verified the first v0.24 remote reference run with 23 tests, 276,249 raw events, 15 manifested portable artifacts and a successful uploaded reference-evidence bundle.

## v0.23.0

- preserved row-level rejection evidence with multi-rule `reject_reason`;
- expanded event certification to unknown products/events and invalid revenue semantics;
- persisted `rejected_events`, `revenue_reconciliation` and `quality_report` in DuckDB;
- added machine-readable event and metric contracts;
- added portable SHA-256 artifact manifests;
- added an independent generated-build validator;
- upgraded CI to build, validate and upload a 120-day reference-evidence artifact;
- excluded the synthetic post-acquisition outcome tail from forecast validation using an explicit observation-maturity cutoff;
- pinned the verified 120-day reference summary after remote CI reproduced 50,581 raw / 589 rejected / 49,992 certified rows and a 3-pass / 6-withhold forecast gate;
- separated current reproducible evidence from preserved historical planning snapshots.

## v0.22.0

- initial compact public release of the product analytics and data reliability workbench.
