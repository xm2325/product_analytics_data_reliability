# Changelog

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
