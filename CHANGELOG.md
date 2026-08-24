# Changelog

## v0.36.0

- added a **real-world external-data portability lane** using the official UCI Online Retail II source rather than extending the synthetic generator;
- made the network-enabled GitHub Actions workflow download the public UCI source directly, while keeping the raw workbook out of the repository and uploaded evidence bundle;
- pinned the accepted source archive at **45,622,418 bytes / SHA-256 `572e36277c2390fbfde10664750731e0a86f55e33470d91919085f0408e67bfb`** and the extracted workbook at **45,622,278 bytes / SHA-256 `bcbe73b35f5b7babf197fb0cb983a11f5d9ff929078d4aa53d171b1f2df2e980`**, so upstream replacement requires explicit review;
- added a source adapter for both workbook vintages, including `Invoice`/`InvoiceNo`, `Price`/`UnitPrice` and `Customer ID`/`CustomerID` aliases, and mapped **1,067,371** source rows to one canonical transaction representation;
- added a real-data quality report covering **243,007 missing CustomerID rows, 19,494 cancellations, 22,950 non-positive quantities, 6,207 non-positive unit prices and 12,133 exact duplicate rows** excluding the generated source-row identifier;
- defined a source-specific purchase metric contract and built a continuous **739-day** daily layer for purchase revenue, orders, units, purchase lines and identifiable active customers;
- fixed a real-data portability bug found by CI: days containing anonymous valid purchases but no identifiable customer previously produced `NaN` active customers after the identity join; the metric now correctly records **0 identifiable active customers**;
- tested two candidate semantic drop-in replacements against the declared 1% compatibility tolerance: signed transaction value moves purchase revenue by **-8.04%** and any-transaction customer population moves the purchasing-customer population by **+1.09%**, so both are **WITHHOLD_AS_DROP_IN_REPLACEMENT**;
- reused the frozen v0.35 forecast contract without post-hoc tuning on four external series; all four candidates beat the last-value benchmark on WAPE but **0/4 are planning-approved** because at least one absolute-accuracy gate remains failed;
- retained the strongest real-data boundary case: `orders` has **15.31% WAPE** and about **59% lower WAPE than the last-value benchmark**, but **20.94% MAPE** exceeds the pre-existing 20% limit, so the decision stays **WITHHOLD**;
- added `validate_real_retail_reference.py`, which re-extracts and reloads all source rows, recomputes quality and daily metrics in DuckDB SQL, and independently rebuilds semantic and forecast decisions;
- added `results/real_data_reference_summary.csv` plus `validate_real_static_claims.py`, binding public real-data claims to generated evidence in CI;
- added a separate `real-data` workflow and `make real-check`; the default synthetic `make check` remains separate so controlled point-in-time evidence does not depend on network access;
- explicitly refused to claim real-data late-arrival/watermark validation because UCI Online Retail II exposes invoice/event time but no separate ingestion timestamp;
- advanced package/runtime version metadata to **0.36.0** and the full repository test suite from **81 to 84 tests**, while preserving the v0.35 controlled reference with **53 SHA-256-manifested artifacts**.

## v0.35.0

- added a **contract-evolution and metric-change governance** layer so a technically green pipeline is no longer treated as evidence that a schema or KPI migration is semantically safe;
- classified **ADDITIVE**, **BREAKING** and **SEMANTIC** migrations and evaluated three deterministic proposals: optional `country` **APPROVE**, required `event_id -> event_uuid` **WITHHOLD**, and broadening DAU from `app_open` to any certified event **WITHHOLD**;
- added a **450-row shadow replay** across three products × 150 Gold days and measured aggregate DAU shifts of **+4.94%, +2.04% and +4.04%** while paid/revenue controls remained invariant;
- recomputed downstream leakage-safe DAU forecasts under candidate semantics and showed **0/3 forecast eligibility states changed**, demonstrating that stable downstream decisions cannot compensate for a material KPI-definition change;
- added independent migration reconstruction and public claim-ledger validation, aligned package/runtime metadata at 0.35.0, and advanced the controlled suite to **81 tests / 53 manifested artifacts**.

## v0.34.0

- replaced one terminal forecast holdout with **four rolling as-of origins × seven-day horizons** while preserving 28 evaluation points per metric;
- added a last-observation benchmark, WAPE, leakage-safe origin-specific residual intervals and non-compensatory forecast gates;
- made `photo_editor:dau` a deliberate counterexample: **3.92% candidate WAPE** is withheld because the simpler benchmark is better at **2.56%**;
- added independent reconstruction of all **252 row-level forecast points** and advanced the controlled reference to **75 tests / 47 manifested artifacts**.

## v0.33.0

- separated counterfactual product impact from decision-authorised impact after the pricing experiment remained **HOLD**;
- added a 150,000-user hypothetical launch scenario with **£102,762.12** counterfactual 30-day revenue impact while authorised exposure remained zero;
- added conditional paid-guardrail evidence planning with a first passing equal-allocation target of **6,393 users per arm**.

## v0.32.0

- added the deterministic 8,000-user pricing experiment, exact SRM gate, ANCOVA + HC3 primary revenue analysis and paid-conversion non-inferiority guardrail;
- retained a deliberately non-compensatory **HOLD** despite positive revenue evidence because the paid-conversion confidence interval crosses the harm margin.

## Earlier releases

Earlier release history introduced metric contracts, retention maturity, processing-time/watermark governance, rolling stability, family-wise uncertainty and prospective evidence planning. The complete historical detail remains available in repository history.
