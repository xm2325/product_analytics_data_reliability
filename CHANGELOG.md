# Changelog

## v0.37.0

- converted the v0.36 UCI Online Retail II lane from full-snapshot-only processing into a **recoverable incremental data product** while keeping the same pinned **1,067,371-row** public real source;
- canonicalised the source once into **25 immutable monthly Parquet partitions** with row counts, byte sizes and SHA-256 provenance; the reference canonical store is **9,806,373 bytes**, about 78.5% smaller than the 45,622,278-byte source workbook;
- added durable partition state written after every successful materialisation and a reuse rule requiring source-manifest identity, source row count, complete state and the derived-output SHA to agree;
- made unchanged reruns truly idempotent: the reference no-op processes **0 partitions, scans 0 source rows, computes 0 large-source hashes and changes 0 output hashes**;
- added an interrupted-run recovery scenario that stops after **7 completed partitions / 257,045 durable rows**, then resumes by skipping those 7 partitions and scanning only the remaining **810,326 rows**; resumed output exactly equals uninterrupted output;
- added targeted derived-output repair: corrupting the `2010-12` materialisation rebuilds exactly **1 partition / 65,004 source rows**, a **93.91% scan reduction** versus a full-source rebuild, and restores the exact pre-corruption output hashes;
- added a separate source-revision unit test that changes one canonical month and its manifest, verifies only that month is recomputed, then restores the original month and exact clean-rebuild parity;
- added `validate_incremental_retail_reference.py`, which independently SHA-verifies every canonical source partition, rebuilds daily metrics directly from source Parquet in DuckDB and checks full/incremental/recovery/repair parity and work accounting;
- added `results/incremental_reference_summary.csv` and `validate_incremental_static_claims.py` to pin deterministic performance evidence while deliberately **rejecting wall-clock seconds/speedups as stable public claims**;
- diagnosed the main first-load bottleneck as XLSX decompression/XML parsing and canonical type conversion: one post-optimisation GitHub Actions run observed about **54.99 s** for source parse/normalisation versus **0.100 s** for a clean full DuckDB rebuild from canonical Parquet;
- found and fixed an implementation-level incremental overhead: the first version opened one DuckDB connection per partition and scanned each changed partition once for `COUNT(*)` and again for aggregation; v0.37 now reuses **one DuckDB connection per run** and performs **one aggregation scan per changed partition**;
- after that refactor, observed initial incremental materialisation changed from **0.591 s to 0.269 s** across two diagnostic shared-runner executions (~54.5% lower); these timings are retained as diagnostic evidence only, not a performance SLA;
- retained an explicit expensive full-source integrity audit while making normal no-op processing trust the pinned immutable canonical manifest, so routine idempotent runs do not re-hash every large source partition;
- added `incremental-real-data` GitHub Actions and `make incremental-check`, separate from both the controlled synthetic and v0.36 real-data portability lanes;
- preserved the source-time boundary: `InvoiceDate` drives historical monthly replay but is not represented as ingestion time, so no real-data late-arrival, watermark or arrival-order claim is introduced;
- advanced package/runtime version metadata to **0.37.0** and the full repository suite from **84 to 88 tests** while retaining the v0.35 controlled 53-artifact reference and v0.36 real-data validators.

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
