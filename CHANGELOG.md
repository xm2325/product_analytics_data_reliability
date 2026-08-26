# Changelog

## v0.42.0

- closed the v0.41 stale-evidence loop with **selective evidence revalidation** rather than another forecasting model, framework or dashboard;
- introduced governed revalidation states `NOOP`, `BLOCKED_EXPLICIT_ADOPTION_REQUIRED`, `BLOCKED_PRODUCER_INCOMPATIBLE`, `READY` and `REVALIDATED`, with partial replacement evidence rejected rather than tolerated;
- preserved the frozen v0.35 decision that broadening DAU to any certified event is **WITHHOLD as a silent replacement**; v0.42 does not relax the 1% semantic compatibility tolerance or reinterpret that historical decision;
- modelled a separate explicit, versioned DAU semantic adoption and rebuilt only its eight stale lineage nodes: `semantic:dau`, `metric:dau`, three DAU forecasts and three DAU planning decisions;
- recomputed **450 Gold product-day metric rows**, **3 rolling-origin DAU forecast series** and **3 planning decisions**, while recomputing **0 pricing-chain nodes**;
- required the other **8 / 16** DAG nodes to be reused exactly, including producer shape, revenue/paid semantic and metric evidence, pricing experiment, impact and rollout authorisation;
- independently verified that the explicit semantic adoption moves the graph from **8 stale / 8 fresh** to **0 stale / 16 fresh**, while the silent semantic replacement remains blocked with 8 stale nodes;
- kept the required `event_id -> event_uuid` producer break **BLOCKED_PRODUCER_INCOMPATIBLE** with 13 stale nodes, because downstream recomputation cannot compensate for an unresolved producer contract break;
- rebuilt the candidate DAU forecast evidence from the frozen Gold/Silver layers and cross-checked it against the separately validated v0.35 migration replay: `file_transfer` 5.53% WAPE APPROVE, `notes_app` 4.06% APPROVE, and `photo_editor` 3.77% WITHHOLD because its 2.46% last-value benchmark remains better;
- added `evidence_revalidation.py`, four v0.42 evidence artefacts, five focused unit tests and `validate_evidence_revalidation_reference.py`, whose validation path does not import the production revalidation planner;
- pinned only deterministic work counts and exact reuse/freshness results; no shared-runner latency, QPS, throughput or speedup claim is made;
- advanced repository/package/runtime metadata to **0.42.0** while leaving the frozen v0.35 controlled bundle, reporting data-product version **0.40.0** and response schemas **1.0 / 1.1** unchanged;
- advanced the full repository suite from **106 to 111 tests**.

## v0.41.0

- added **selective downstream evidence invalidation** over the frozen v0.35 controlled decision bundle rather than silently rewriting historical reference evidence;
- introduced a deterministic **16-node evidence dependency DAG** spanning producer shape, DAU/revenue/paid metric semantics, certified metrics, three DAU forecasts, three planning decisions, the pricing experiment, impact plan and rollout authorisation;
- fingerprinted governed dependency surfaces with canonical SHA-256 rather than comparing version labels or one global contract hash, so an unused additive field does not create false-positive invalidation;
- separated evidence freshness from the original business action: stale evidence fails closed as `WITHHOLD_STALE`, while fresh nodes retain their baseline `APPROVE`, `WITHHOLD`, `HOLD` or `COUNTERFACTUAL_ONLY` state;
- replayed the three existing v0.35 migration proposals through the dependency graph: optional `country` leaves **16/16 nodes fresh**, DAU semantic broadening makes **1 node directly stale + 7 downstream stale = 8 stale**, and required `event_id -> event_uuid` makes **1 direct + 12 downstream = 13 stale**;
- demonstrated selective isolation under the DAU semantic change: all DAU metric/forecast/planning evidence becomes stale even though the old v0.35 forecast eligibility result was 0/3 changed, while the unrelated pricing experiment/impact/authorisation chain stays fresh with baseline actions `HOLD`, `COUNTERFACTUAL_ONLY` and `WITHHOLD`;
- added graph validation for duplicate/unknown dependencies and cycles plus five focused unit tests for additive, semantic, breaking and malformed-graph cases;
- added `build_evidence_invalidation_reference.py` and four derived evidence files without modifying the frozen v0.35 `MANIFEST.json` or static claim ledger;
- added `validate_evidence_invalidation_reference.py`, which does **not** import the production invalidation module: it independently reconstructs the DAG, recomputes fingerprints, propagates staleness and checks every generated scenario row and exact scenario counts;
- wired the new build/validator into the controlled GitHub Actions lane and `make check`, while deliberately keeping the reporting data-product version at **0.40.0** and response schemas at **1.0 / 1.1**;
- advanced repository/package metadata to **0.41.0** and documented the claim boundary: deterministic controlled dependency invalidation, not a production lineage catalogue, scheduler or distributed cache-invalidation system.

## v0.40.0

- replaced the v0.39 reporting store's persistent shared DuckDB query connection with **request-local ephemeral DuckDB connections**, keeping source manifest and durable partition state immutable/shared while isolating mutable query-execution state per consumer;
- retained the public consumer contract unchanged: schema **1.0 remains the default**, schema **1.1 remains explicit opt-in**, and v0.40 is a data-product execution upgrade rather than a silent response-schema migration;
- added a deterministic **12-request / 12-consumer** real-data workload over the pinned 1,067,371-row UCI Online Retail II incremental store, mixing one-month, cross-month, year-scale, multi-metric and schema 1.0/1.1 requests;
- compared the serial baseline with an **8-worker concurrent replay** and required exact per-request compact-result parity plus an identical workload SHA-256 fingerprint `ef1adcc2dc091ad9ad00c16175ea7b38c8f6fec084c4c1700c6c50c127376e7e`;
- pinned deterministic work for that workload at **27 aggregate metric partitions selected / 27 selected metric files SHA-verified / 652 response rows / 16 unique partitions touched**;
- added six parallel consumers of the same hot December 2010 query and observed **one unique full-payload hash**, demonstrating that interleaved execution does not change the returned payload;
- added a **15-request mixed failure workload** by injecting unknown-metric, unsupported-schema and duplicate-metric consumers; all **3/3** invalid requests fail through `ReportingContractError` while every healthy result remains identical to its serial baseline;
- required a second healthy serial replay after the mixed failure batch, proving that failed consumers do not leave shared query state that changes subsequent answers;
- added `workload_isolation.py`, `build_workload_isolation_reference.py`, real workload request/result/evidence artefacts, and `tests/test_workload_isolation.py`;
- added `validate_workload_isolation_reference.py`, which does **not** import the workload harness: it independently runs serial/threaded replays, reconciles successful responses to `incremental_daily_metrics.csv`, recomputes response hashes and work accounting, and checks the exact failure set;
- added `results/workload_isolation_reference_summary.csv` and `validate_workload_static_claims.py`, deliberately refusing checked-in `seconds`, `latency`, `qps`, `throughput` or `speedup` claims from shared GitHub runners;
- kept the claim boundary explicit: this is deterministic single-node DuckDB/Parquet consumer isolation evidence, not a network-service throughput SLA, distributed-database isolation claim, tenant-fairness proof or capacity benchmark;
- let CI catch and repair one validator-quality regression during development: the first v0.40 reporting validator matched an explanatory sentence too literally; it now checks the actual structural isolation promises without weakening any execution or parity gate;
- advanced package/runtime/reporting metadata to **0.40.0**, advanced the focused operational suite from **15 to 17 tests**, and advanced the full repository suite from **99 to 101 tests**, while the prior controlled, real-data, incremental, reporting and contract-evolution validators remain green.

## v0.39.0

- added **governed consumer-contract evolution** over the v0.38 reporting data product, keeping the data-product release version separate from the public response-schema version;
- preserved JSON schema **1.0 as the default** so existing/unversioned consumers are not silently migrated, while adding explicit opt-in schema **1.1** through `--schema-version 1.1`;
- made schema 1.1 strictly additive over 1.0: the existing nine top-level fields remain unchanged and one new top-level `contract` object exposes the schema family, negotiated version, explicit backward-compatibility path and deterministic metric-catalogue SHA-256;
- kept the stable response hash defined over the query plus metric rows, so the same real-data request produces identical query payload, metric rows, response SHA-256 and deterministic partition work under schema 1.0 and 1.1;
- added field-level schema specifications covering the top-level response, query, availability, partition provenance, row base fields, metric types and 1.1 contract metadata;
- added three governed migration proposals: additive `contract` metadata is **APPROVE**, while renaming `row_count` to `rows` and changing `orders` from integer to float are both **BREAKING / WITHHOLD**;
- made removals, renames and type changes non-compensatory consumer gates rather than allowing an otherwise useful release to overwrite a published contract;
- added a strict response-shape check before responses leave the reporting layer and fail-closed rejection of unsupported schema versions;
- added a real UCI compatibility replay using the seven-day `2010-12-01` to `2010-12-07` query; schema 1.0 and 1.1 retain exact query/data/hash/work parity and schema 1.1 adds only the declared `contract` envelope;
- added `build_consumer_contract_reference.py`, serialised schema registry/migration/sample-response evidence, and `results/consumer_contract_reference_summary.csv`;
- added `validate_consumer_contract_reference.py`, an independent validator that does **not** import the production classifier: it reconstructs field maps, recomputes all migration classifications/actions, independently recomputes both response hashes and independently recomputes the metric-catalogue SHA;
- extended the operational GitHub Actions lane to run default schema 1.0, explicit schema 1.1 and CSV smoke tests after the existing 1,067,371-row incremental/reporting evidence chain;
- kept the compatibility claim explicit: additive does not mean every possible parser accepts unknown fields; strict old consumers retain schema 1.0 negotiation, and no production deprecation/support-lifetime SLA is claimed;
- advanced package/runtime metadata to **0.39.0**, advanced the focused incremental/reporting/contract suite to **15 tests**, and advanced the full repository suite from **93 to 99 tests** while keeping the v0.35–v0.38 evidence gates intact.

## v0.38.0

- added a **versioned consumer reporting data product** over the validated v0.37 UCI incremental metric store rather than adding another model or presentation layer;
- exposed five allowlisted daily metrics — `revenue_gbp`, `orders`, `units`, `purchase_lines` and `active_customers` — through a framework-independent Python interface plus JSON/CSV CLI;
- defined reporting schema **1.0**, explicit historical availability, deterministic response SHA-256, zero-filled missing calendar days and a bounded **366-day** maximum request window;
- made invalid requests fail closed: unknown/duplicate metrics, reversed ranges, dates outside the historical store and over-wide requests are rejected before metric values are returned;
- bound selected metric partitions back to the canonical source manifest and durable v0.37 state, requiring complete status, source SHA/row-count identity, metric-file existence and metric SHA agreement before serve;
- strengthened integrity ordering after the first CI attempt found that a corrupted boundary Parquet could reach DuckDB's date-bound read before the metric SHA guard; boundary integrity is now verified **before DuckDB opens the file**, producing the reporting contract's own fail-closed error rather than a parser exception;
- retained a separate real-data tamper case on middle partition `2010-12`, proving that a normally selected corrupted partition is also rejected at query time;
- validated a seven-day real query (`2010-12-01` to `2010-12-07`) against the existing daily layer with **exact response parity** while selecting **1 of 25** monthly metric partitions for metric values, a **96% metric-partition-selection reduction** relative to selecting all 25;
- validated a cross-month query that selects exactly **2** metric partitions and pinned the reporting store's historical availability at **2009-12-01 through 2011-12-09**;
- kept the performance claim narrow: store initialisation separately checks/reads the first and last boundary partitions, and 96% is neither an end-to-end latency claim nor a source-row reduction claim;
- added `build_reporting_product_reference.py`, `validate_reporting_product_reference.py`, `results/reporting_reference_summary.csv` and JSON/CSV CLI smoke tests; the independent validator reconstructs response rows and digests without importing the reporting module;
- kept the source-time boundary explicit: UCI has event/invoice time but no separate ingestion timestamp, so the data product does not claim real point-in-time/as-of reconstruction, production freshness or network-service SLA behaviour;
- advanced package/runtime metadata to **0.38.0** and the full repository test suite from **88 to 93 tests** while preserving the v0.35 controlled, v0.36 portability and v0.37 recovery/performance evidence lanes.

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
- diagnosed the main first-load bottleneck as XLSX decompression/XML parsing and canonical type conversion; shared-runner timings remain diagnostic rather than public performance gates;
- retained an explicit expensive full-source integrity audit while making normal no-op processing trust the pinned immutable canonical manifest, so routine idempotent runs do not re-hash every large source partition;
- added `incremental-real-data` GitHub Actions and `make incremental-check`, separate from both the controlled synthetic and v0.36 real-data portability lanes;
- preserved the source-time boundary: `InvoiceDate` drives historical monthly replay but is not represented as ingestion time, so no real-data late-arrival, watermark or arrival-order claim is introduced;
- advanced package/runtime version metadata to **0.37.0** and the full repository suite from **84 to 88 tests** while retaining the v0.35 controlled 53-artifact reference and v0.36 real-data validators.

## v0.36.0

- added a **real-world external-data portability lane** using the official UCI Online Retail II source rather than extending the synthetic generator;
- made the network-enabled GitHub Actions workflow download the public UCI source directly, while keeping the raw workbook out of the repository and uploaded evidence bundle;
- pinned the accepted source archive at **45,622,418 bytes / SHA-256 `572e36277c2390fbfde10664750731e0a86f55e33470d91919085f0408e67bfb`** and the extracted workbook at **45,622,278 bytes / SHA-256 `bcbe73b35f5b7babf197fb0cb983a11f5d9ff929078d4aa53d171b1f2df2e980`** so upstream replacement requires explicit review;
- mapped **1,067,371** source rows to one canonical transaction representation and added real-data quality, metric semantics and frozen forecast validation;
- fixed a real-data portability bug where anonymous-only purchase days produced `NaN` active customers, representing them correctly as **0 identifiable active customers**;
- tested two semantic replacements against the declared 1% compatibility tolerance: signed transaction value moves purchase revenue by **-8.04%** and any-transaction customer population changes the purchasing-customer population by **+1.09%**, so both are withheld as silent drop-ins;
- reused the frozen v0.35 forecast contract without post-hoc tuning; **0/4** external forecast metrics are planning-approved, including the useful `orders` boundary case with **15.31% WAPE** but **20.94% MAPE** above the frozen 20% gate;
- added independent DuckDB/Python real-data reconstruction and checked-in public claim validation;
- explicitly refused to claim real-data late-arrival/watermark validation because UCI Online Retail II exposes invoice/event time but no separate ingestion timestamp;
- advanced package/runtime metadata to **0.36.0** and the full repository test suite from **81 to 84 tests**.

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
- added conditional paid-guardrail evidence planning with a first passing equal-allocation target of **6,393 users per arm**, +2,393 per arm from the current 4,000.

## v0.32.0

- added the deterministic 8,000-user pricing experiment, exact SRM gate, ANCOVA + HC3 primary revenue analysis and paid-conversion non-inferiority guardrail;
- retained a deliberately non-compensatory **HOLD** despite positive revenue evidence because the paid-conversion confidence interval crosses the harm margin.

## Earlier releases

Earlier release history introduced metric contracts, retention maturity, processing-time/watermark governance, rolling stability, family-wise uncertainty and prospective evidence planning. The complete historical detail remains available in repository history.
