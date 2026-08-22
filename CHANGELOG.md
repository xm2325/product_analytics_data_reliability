# Changelog

## v0.25.0

- introduced an auditable retention-maturity ledger for every product × cohort-date × D7/D30 horizon;
- made `analysis_as_of` a shared reporting boundary and prevented simulator-generated future `app_open` events from leaking into immature retention cohorts;
- separated `cohort_users`, `eligible_users` and `excluded_users` so evidence maturity is not confused with user churn;
- added machine-readable D7/D30 retention contracts with exact-calendar-day return windows and explicit mature-cohort denominators;
- kept existing retention outputs as backward-compatible mature-only views derived from the ledger;
- added a maturity summary showing mature/immature cohorts and eligible-user fractions by horizon;
- independently recomputed the maturity ledger in DuckDB SQL and added Python↔SQL parity tests;
- strengthened build validation for date boundaries, denominator accounting, null future outcomes, exclusion reasons and D30-vs-D7 maturity ordering;
- fixed explicit ISO serialization of reporting dates and normalized nullable parity comparisons to avoid future pandas compatibility failures;
- verified the v0.25 remote reference with **29 tests**, successful build validation, **18 SHA-256-manifested portable artifacts**, and an uploaded reference-evidence bundle.

## v0.24.0

- introduced explicit `app_open` activity events and product-specific decaying return behaviour;
- isolated activity randomness from the commercial RNG so acquisition/trial/paid/purchase reference outcomes remain unchanged;
- migrated current DAU to `unique users with app_open` (metric contract v2.0) while retaining the any-event DAU as `v1.0-deprecated` for dual-run comparison;
- generated daily DAU migration evidence and product-level migration summaries;
- added D7/D30 activity-retention cohorts and weighted summaries;
- updated forecasting to consume DAU v2 while preserving the existing observation-maturity cutoff;
- aligned DuckDB SQL Silver/Gold logic with the current Python contracts and added Python↔SQL parity tests;
- expanded reference-build validation to cover activity events, DAU contract versions, migration direction, retention bounds/decay and product activity configuration.

## v0.23.0

- preserved row-level rejection evidence with multi-rule `reject_reason`;
- expanded event certification to unknown products/events and invalid revenue semantics;
- persisted `rejected_events`, `revenue_reconciliation` and `quality_report` in DuckDB;
- added machine-readable event and metric contracts;
- added portable SHA-256 artifact manifests;
- added an independent generated-build validator;
- upgraded CI to build, validate and upload a 120-day reference-evidence artifact;
- excluded the synthetic post-acquisition outcome tail from forecast validation using an explicit observation-maturity cutoff;
- separated current reproducible evidence from preserved historical planning snapshots.

## v0.22.0

- initial compact public release of the product analytics and data reliability workbench.
