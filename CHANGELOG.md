# Changelog

## v0.34.0

- replaced the single terminal 28-point forecast holdout with **four rolling as-of origins × seven-day horizons**, preserving 28 evaluation points per product × metric while making the evidence explicitly time-ordered;
- retained the transparent weekly seasonal-naive candidate and added a simpler **last-observation benchmark**, so low absolute error is no longer sufficient for planning eligibility when a trivial baseline performs better;
- replaced MAPE-only decisioning with a non-compensatory forecast contract requiring sufficient backtest depth, **MAPE/WAPE ≤ 20%**, candidate WAPE no worse than the benchmark, and at least **85% empirical coverage** for the nominal 90% residual interval;
- added leakage-safe origin-specific interval calibration using only pre-origin lag-7 residuals and an explicit finite-sample order statistic `ceil((n + 1) * (1 - alpha))`, capped at the calibration sample size;
- added a hard guard against forecast horizons longer than the seasonal lag, preventing future holdout values from becoming lag sources;
- generated `forecast_contract.json`, `forecast_backtest.csv` and `forecast_reconciliation.csv`, and upgraded `forecast_evaluations.csv` to carry candidate, benchmark, coverage and individual gate evidence;
- added historical seven-day plan-vs-actual reconciliation while explicitly refusing to construct a false aggregate 90% interval by summing marginal daily intervals;
- made the deterministic reference intentionally stricter: **2 metrics approved / 7 withheld**; `file_transfer:dau` and `notes_app:dau` remain eligible, while `photo_editor:dau` is withheld despite **3.92% WAPE** because the last-value benchmark is better at **2.56% WAPE**;
- added `validate_forecast_plan.py`, which independently reconstructs all **252 row-level rolling-origin forecast points** from lower-level Gold/Silver evidence and recomputes source dates, candidate and benchmark errors, intervals, gate states and reconciliation;
- refactored the reference build into a two-stage orchestrator so the validated v0.33 experiment/impact/watermark evidence is preserved, then upgraded with v0.34 forecast evidence before the final manifest is re-hashed;
- removed an inappropriate release-version coupling from `validate_impact_plan.py`: the validator now protects the stable impact contract and evidence invariants rather than requiring the entire workbench to remain v0.33;
- advanced the package/reference version to **0.34.0**, the deterministic unit-test suite to **75 tests**, and the SHA-256 reference manifest to **47 portable artifacts**;
- verified the complete remote CI chain on GitHub Actions, including build, forecast, watermark, uncertainty, evidence-plan, experiment, impact, pinned-claim and static-ledger validators, with a validated reference-evidence artifact bundle.

## v0.33.0

- added a decision-aware impact-planning layer downstream of the v0.32 pricing experiment without changing the reference experiment's **HOLD** action;
- added three synthetic 30-day launch cohorts with 100,000 eligible users each and hypothetical adoption shares of 25%, 50% and 75%, for **150,000 counterfactual treated users** in total;
- propagated the experiment's 30-day ANCOVA revenue effect and confidence interval into the fixed-volume scenario, producing **£102,762.12** counterfactual incremental revenue with a 95% interval of **[£82,714.46, £122,809.79]**;
- explicitly separated counterfactual impact from decision-authorised impact: because the experiment remains HOLD, authorised treated users are **0** and authorised incremental revenue is **null**;
- added a conditional paid-conversion evidence planner that preserves the experiment's `ddof=1` difference-in-proportions confidence-interval convention rather than silently switching variance definitions;
- pinned the first equal-allocation arm size whose projected lower confidence bound clears the -3pp guardrail at **6,393 users per arm**, or **2,393 additional users per arm** relative to the current 4,000/arm reference, conditional on the observed arm rates remaining representative;
- added an explicit structural-failure state when the observed conversion point estimate itself is at or below the harm margin, because more sample alone cannot repair that case under unchanged planning rates;
- generated `pricing_impact_scenario.csv`, `pricing_impact_contract.json`, `pricing_guardrail_evidence_plan.json` and `pricing_impact_decision.json` and included them in the reference summary and SHA-256 manifest;
- added `validate_impact_plan.py`, which independently recomputes the paid-conversion CI, audits the 6,393/6,392 integer boundary, verifies the launch ramp and checks `HOLD -> counterfactual_only -> zero authorised exposure`;
- refocused the checked-in public claim ledger on headline decision evidence and bound it to generated v0.33 evidence with the static-claim validator;
- advanced the package/reference version to **0.33.0**, the unit-test suite to **68 tests**, and the reference manifest to **44 portable artifacts**.

## v0.32.0

- added a deterministic 8,000-user pricing experiment with exact 4,000/4,000 treatment allocation and an exact two-sided sample-ratio-mismatch gate at `alpha = 0.001`;
- added ANCOVA with pre-period revenue adjustment and HC3 robust standard errors for the 30-day revenue primary metric;
- added a 30-day paid-conversion non-inferiority guardrail with a pre-specified **-3 percentage-point** harm margin and non-compensatory decision semantics;
- introduced explicit `invalid`, `hold` and `rollout` experiment states so assignment-integrity failures cannot be reinterpreted as ordinary business holds;
- made the deterministic reference intentionally **HOLD** despite a positive revenue effect: revenue **+£0.6851** with 95% CI **[£0.5514, £0.8187]**, paid conversion **-1.625pp** with 95% CI **[-3.363pp, +0.113pp]**, so the point estimate is inside the harm margin but the lower confidence bound crosses it;
- generated user-level experiment evidence, estimate, contract and decision artifacts and included them in `reference_summary.json` and the SHA-256 manifest;
- added an independent pricing-experiment validator that recomputes SRM, ANCOVA + HC3 uncertainty, paid-conversion uncertainty and decision gates from the user-level artifact instead of trusting generated estimates;
- tightened treatment validation so fractional values such as `0.5` cannot be silently coerced to control via integer casting;
- extended `make check` and GitHub Actions with the experiment validation layer;
- advanced the package/reference version to **0.32.0**, the unit-test suite to **63 tests**, and the reference manifest to **40 portable artifacts**.

## v0.31.0

- replaced single-point prospective exact-bound targets with cycle-stable targets that must remain passing across the next full `ceil(1 / planning_rate)` adverse-count jump cycle;
- made the statistical claim boundary explicit with `global_monotonic_threshold_claimed = false` rather than implying that all larger sample sizes necessarily pass;
- introduced one shared count-jump-cycle function for the generator and validator, using an **8-ULP** reciprocal-integer boundary so CSV/pandas round-trips are normalized without rounding genuine near-integer reciprocals downward;
- added regression tests for the 135- and 333-position round-trip boundaries, genuine non-integer cycles, and a deliberately close reciprocal that must still map to 136;
- updated the deterministic reference targets: 48h late events **99,573,018**, 72h revised cells **14,989**, 96h late events **2,733,153**, 96h revised cells **2,011**, and 96h combined planning depth **1,330 days (~3.64 years)**;
- pinned the 96h audited cycles at **206 late-event positions** and **333 revised-cell positions** in the public claim validator;
- aligned the reference-summary version with package version **0.31.0** and updated public evidence documentation;
- increased the unit-test suite to **57 tests** while retaining the full build, rolling-backtest, uncertainty, evidence-plan and pinned-claim validation chain.

## v0.30.0

- added prospective certification evidence planning after the v0.29 family-wise analysis returned no certified candidate;
- separated underlying rate failures and deterministic hard-gate breaches from gaps that can be addressed by more proportional evidence alone;
- retained the 72 simultaneous one-sided bounds, unchanged risk budget and no weighted score;
- identified 96h as the only evidence-depth-only candidate under the reference assumptions;
- reported the original single-point 96h planning target of **2,718,757 events**, **1,853 KPI cells** and **1,323 days** of evidence depth.

## v0.29.0

- added one-sided exact Clopper–Pearson upper bounds for late-event and revised-KPI-cell proportions across all candidate-window rows;
- applied a 95% family-wise Bonferroni rule over **72 simultaneous one-sided bounds**;
- kept deterministic revenue and paid-subscription maximum revisions as separate hard gates;
- showed that no candidate is statistically certified under the declared family-wise rule even though 96h is observed feasible in every rolling window.

## v0.28.0

- added nine weekly processing-time snapshots and rolling watermark-policy backtesting;
- separated final-snapshot feasibility from all-window observed stability;
- identified **48h** as the shortest feasible candidate at the final snapshot and **96h** as the shortest candidate feasible in all nine rolling windows;
- added rolling-policy validators and machine-readable stability evidence.

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
