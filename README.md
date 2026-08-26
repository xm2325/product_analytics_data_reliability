# Product Analytics & Data Reliability Workbench

**Version:** v0.43  
**Stack:** Python · DuckDB · SQL · Pandas · NumPy · SciPy · Statsmodels · Parquet · Pytest · GitHub Actions

A reproducible analytics workbench for deciding when data, metrics, forecasts and experiments are trustworthy enough to support a business decision — and for keeping those decisions trustworthy as upstream data, KPI definitions, source records, consumer contracts and concurrent workloads evolve.

The repository is organised around one principle:

> **A result is not trustworthy merely because it was correct when first computed. It must still be supported by the governed evidence assumptions and source records in force when someone acts on it.**

The evidence chain now covers nine complementary layers:

```text
controlled decision evidence
    -> data quality, point-in-time correctness, metrics, forecasting,
       experiment guardrails, impact and decision boundaries

metric / producer change governance
    -> additive, semantic and breaking migration classification
       plus shadow replay and frozen compatibility thresholds

selective evidence invalidation
    -> dependency fingerprints, lineage-aware stale propagation,
       fail-closed downstream actions and false-positive avoidance

selective evidence revalidation
    -> explicit adoption, minimal rebuild sets, exact unaffected reuse,
       independent recovery verification and fail-closed blocked states

source-incident correction and decision supersession
    -> keyed correction ledger, affected-scope derivation,
       selective replay, clean-rebuild parity and historical decision lineage

public real-world evidence
    -> UCI schema adaptation, source quality, metric semantics,
       frozen forecast portability and independent recomputation

real-world operational evidence
    -> immutable partitions, incremental processing, idempotency,
       interruption recovery, targeted repair and deterministic work accounting

consumer data-product / contract evidence
    -> bounded historical queries, provenance, integrity-before-serve,
       schema negotiation and breaking-change gates

multi-consumer execution evidence
    -> request-local query engines, serial/concurrent exact parity,
       deterministic work accounting and failure isolation
```

## v0.43 headline: a valid-looking source error can invalidate a published decision

v0.37 proves technical recovery from incomplete or damaged materialisation. v0.42 proves selective revalidation after an explicitly governed semantic change. v0.43 covers a different failure mode:

> **What happens when source records passed the row-level contract, were used in downstream evidence, and are only later discovered to be factually misrouted?**

The controlled incident relabels every `notes_app` `app_open` in one historical seven-day forecast horizon as `file_transfer`. Event IDs, event types, timestamps and revenue remain valid, so ordinary row-level quality checks reject **0 rows**. The error is business-semantic, not syntactic.

### Validated incident and repair

| v0.43 controlled evidence | Result |
|---|---:|
| Incident dates | **2026-04-10 to 2026-04-16** |
| Schema-valid misrouted events | **5,543** |
| Row-level quality rejects | **0** |
| Affected products | **2** |
| Affected Gold product-days | **14** |
| Total Gold product-days | **450** |
| Gold rows selectively recomputed | **14** |
| Gold rows reused | **436** |
| Gold rows not recomputed | **96.89%** |
| Forecast series recomputed | **2** |
| Forecast series reused | **1** |
| Published decisions superseded | **2** |
| Superseded decisions whose action changed | **2** |
| Unaffected decisions retained | **1** |

The 96.89% figure is deterministic **Gold-row recomputation reduction**, not a latency or speedup claim.

### Correction fails closed

The correction ledger is keyed by `event_id`. A correction is rejected if it contains duplicate or unknown IDs, or if the current incident rows no longer match the declared incident product, event type or event date. A stale or tampered correction therefore cannot silently rewrite history.

The ledger determines the affected scope explicitly:

```text
5,543 corrected event_ids
        ↓
2 products × 7 dates
        ↓
14 Gold product-day rows
        ↓
2 DAU forecast series
        ↓
2 published planning decisions
```

`photo_editor` is outside that lineage and its forecast/decision evidence is reused rather than recomputed.

### Selective replay must equal a clean rebuild

The core release gate is not merely that the repair “looks plausible”. v0.43 requires:

```text
corrected Silver == clean source Silver                  exact
selectively repaired Gold == clean full Gold rebuild    exact
selectively replayed forecasts == clean full forecasts  exact
```

The Gold equality includes the product/date key set, values and final dtypes. Historical CSV evidence is compared separately with an explicit `1e-12` absolute tolerance only at the decimal text serialisation boundary; that tolerance is not used for targeted-vs-clean replay parity.

### Published decisions are superseded, not overwritten

When corrected evidence changes a published forecast, the old planning record remains present as `SUPERSEDED` and points to a new `ACTIVE` replacement with reason `SOURCE_DATA_CORRECTION`. If evidence is unaffected, no artificial replacement version is created; the original decision remains `ACTIVE_UNCHANGED`.

In the controlled incident both affected DAU planning actions are wrong under the incident state and both recover after correction, so **2/2 superseded decisions also have an action change**. The unrelated `photo_editor:dau` decision remains exactly reusable.

The independent validator does not import `product_analytics.incident_recovery`. It reconstructs the incident, correction, Gold aggregation, targeted row stitching, forecasting evidence, supersession cardinality and hashes independently, and independently restores clean-rebuild dtypes before requiring exact replay parity.

See [`docs/INCIDENT_RECOVERY.md`](docs/INCIDENT_RECOVERY.md).

## v0.42: stale evidence must be selectively rebuilt before reuse

v0.41 answers which evidence becomes stale when a governed dependency changes. v0.42 asks whether it can be recovered with the smallest governed rebuild.

A DAU semantic change makes eight of 16 evidence nodes stale: `semantic:dau`, `metric:dau`, three DAU forecasts and three planning decisions. The producer shape, revenue/paid evidence and pricing chain remain unaffected.

The frozen v0.35 proposal to broaden DAU from `app_open` to any certified event changed portfolio DAU by up to **+4.94%**, above the pre-specified **1% semantic compatibility tolerance**, so silent replacement remains **WITHHOLD**. v0.42 models a separate explicit, versioned semantic-adoption event; only then is selective revalidation allowed.

| Scenario | Initial stale | Revalidated | Exact reused | Final stale | Result |
|---|---:|---:|---:|---:|---|
| optional `country` | 0 | 0 | 16 | 0 | **NOOP** |
| DAU silent replacement | 8 | 0 | 8 | 8 | **BLOCKED** |
| explicit versioned DAU adoption | 8 | 8 | 8 | 0 | **REVALIDATED** |
| required `event_id → event_uuid` producer break | 13 | 0 | 3 | 13 | **BLOCKED** |

The explicit adoption recomputes 450 Gold product-day rows, three DAU forecast series and three planning decisions while reusing the other 8/16 DAG nodes exactly. The candidate forecast actions remain evidence-driven: `file_transfer` 5.53% WAPE APPROVE, `notes_app` 4.06% APPROVE, and `photo_editor` 3.77% WITHHOLD because its 2.46% last-value benchmark is better.

See [`docs/EVIDENCE_REVALIDATION.md`](docs/EVIDENCE_REVALIDATION.md).

## v0.41: upstream changes invalidate only the evidence they actually break

v0.41 introduced a 16-node dependency DAG with canonical SHA-256 fingerprints over governed dependency surfaces.

| Change | Existing migration action | Fresh | Direct stale | Downstream stale | Total stale | Pricing chain fresh |
|---|---|---:|---:|---:|---:|---|
| add optional `country` | **APPROVE** | 16 | 0 | 0 | 0 | yes |
| broaden DAU to any certified event | **WITHHOLD** | 8 | 1 | 7 | 8 | yes |
| rename required `event_id → event_uuid` | **WITHHOLD** | 3 | 1 | 12 | 13 | no |

The DAU case is deliberately important: v0.35 observed 0/3 forecast eligibility changes, yet the old DAU forecasts are still stale because their KPI semantics changed. Unchanged output cannot make stale evidence fresh.

See [`docs/EVIDENCE_INVALIDATION.md`](docs/EVIDENCE_INVALIDATION.md).

## v0.40: concurrent consumers must not change the answer

The reporting store keeps immutable manifest/state metadata shared while every request creates its own DuckDB connection. On the pinned 1,067,371-row UCI source, 12 valid consumers replay exactly under eight workers; a 15-request mixed workload isolates all 3/3 injected invalid consumers; 652 aggregate response rows and 27 selected metric partitions are identical to serial execution. Six consumers of the same hot window produce one unique full-payload hash.

No QPS, latency, throughput or speedup gate is claimed from shared GitHub runners.

See [`docs/WORKLOAD_ISOLATION.md`](docs/WORKLOAD_ISOLATION.md).

## v0.39: evolve the interface without silently migrating consumers

Schema 1.0 remains the default; schema 1.1 is explicit opt-in. Additive contract metadata is approved, while renaming `row_count → rows` and changing `orders` integer → float are breaking and withheld. The same real-data request preserves query payload, metric rows, response SHA and deterministic partition work under both schemas.

See [`docs/CONSUMER_CONTRACT_EVOLUTION.md`](docs/CONSUMER_CONTRACT_EVOLUTION.md).

## v0.38: bounded reporting data product

Five allowlisted daily metrics — `revenue_gbp`, `orders`, `units`, `purchase_lines`, `active_customers` — are exposed through a Python interface and JSON/CSV CLI. The store covers 2009-12-01 through 2011-12-09 and bounds requests to 366 days. The pinned seven-day query selects 1 of 25 metric partitions, a 96% partition-selection reduction, not a latency claim.

See [`docs/REPORTING_DATA_PRODUCT.md`](docs/REPORTING_DATA_PRODUCT.md).

## v0.37: incremental recovery and targeted repair

The real source is canonicalised into 25 immutable monthly Parquet partitions with row counts and SHA-256 provenance. Unchanged reruns scan 0 source rows. Interrupted recovery reuses seven completed partitions / 257,045 rows. Repairing corrupted `2010-12` scans only 65,004 rows, a 93.91% source-row scan reduction versus full rebuild, then restores exact output hashes.

See [`docs/INCREMENTAL_RECOVERY_PERFORMANCE.md`](docs/INCREMENTAL_RECOVERY_PERFORMANCE.md).

## v0.36: external real-world portability

The external lane uses official **UCI Online Retail II** historical transactions. The source contains 1,067,371 rows. Frozen decision rules are not retuned after seeing real data: all four external forecast series are withheld; `orders` has 15.31% WAPE but 20.94% MAPE, just above the frozen 20% gate. Signed transaction value changes purchase revenue by -8.04%, and an any-transaction customer population changes the purchasing-customer population by +1.09% against the declared 1% compatibility threshold; both silent semantic replacements are withheld.

See [`docs/REAL_DATA_PORTABILITY.md`](docs/REAL_DATA_PORTABILITY.md).

## Controlled decision evidence

Synthetic controlled evidence remains where the public source lacks fields required for clean counterexamples.

- **Metric / producer evolution — v0.35:** 450 product-day shadow replay; optional `country` approved; required event-ID rename and DAU semantic broadening withheld.
- **Forecast decisioning — v0.34:** four rolling origins × seven-day horizons; `photo_editor:dau` is withheld despite 3.92% WAPE because the last-value benchmark is better at 2.56%.
- **Experiment / impact — v0.32–v0.33:** deterministic 8,000-user pricing experiment estimates +£0.6851/user/30d with a positive 95% CI, but the paid-conversion guardrail fails, so the experiment remains HOLD. A hypothetical 150,000-user plan implies about £102,762 counterfactual incremental revenue; authorised treated users remain 0.
- **Freshness uncertainty:** 96h is observed stable over nine rolling windows, but no candidate is family-wise certified at 95% under the declared model.

## Validation architecture

Historical evidence boundaries remain explicit instead of being rewritten by later releases.

```text
controlled deterministic lane
  pytest (117 repository tests)
  → frozen v0.35 reference build
  → forecast / migration validators
  → v0.41 dependency graph + independent invalidation validator
  → v0.42 selective rebuild + independent revalidation validator
  → v0.43 source incident build + independent correction/replay validator
  → watermark / uncertainty / evidence-plan validators
  → experiment / impact validators
  → frozen v0.35 pinned/static claim validators

real-data portability lane
  official pinned UCI download
  → source adapter / quality / metrics
  → semantic and frozen forecast evidence
  → independent DuckDB/Python recomputation
  → checked-in real-data claim ledger

operational consumer lane
  official pinned UCI download
  → 25-partition canonical store
  → no-op / interruption / repair evidence
  → bounded reporting + integrity-before-serve
  → schema 1.0 default / explicit 1.1 negotiation
  → request-local DuckDB execution
  → serial vs 8-worker concurrent exact replay
  → mixed invalid-consumer failure isolation
  → independent workload recomputation
```

## Reproduce

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -e .

make check
make real-check
make incremental-check
```

The controlled governance/recovery layers can also be run directly after the controlled reference:

```bash
make reference
make invalidation-reference
make invalidation-validate
make revalidation-reference
make revalidation-validate
python scripts/build_incident_recovery_reference.py --base-dir build/reference --output-dir build/incident-recovery
python scripts/validate_incident_recovery_reference.py --base-dir build/reference --output-dir build/incident-recovery
```

## Claim boundaries

- UCI Online Retail II is public real-world historical data; this repository is not a production deployment and does not claim access to private company systems.
- v0.43 is a **controlled source-incident counterexample**. The 5,543 misrouted events are deliberately injected into frozen controlled evidence; they are not a claim about a real company incident.
- v0.43 proves keyed correction, affected-scope derivation, selective replay, decision supersession and exact clean-rebuild parity in this controlled system. It is not a production CDC platform, distributed lineage scheduler or incident-management service.
- The v0.43 **96.89%** figure is deterministic Gold rows avoided during recomputation (436/450), not wall-clock speedup, latency reduction, QPS or throughput.
- The frozen v0.35 DAU semantic proposal remains WITHHOLD as a silent replacement. v0.42 explicit adoption is a separate governance event, not a post-hoc relaxation of the 1% tolerance.
- Repository/package version **0.43.0** does not rewrite the frozen v0.35 controlled bundle, reporting data-product version **0.40.0**, or response schemas **1.0 / 1.1**.
- `InvoiceDate` is event time, not ingestion time. Real-data late-arrival, watermark, processing-time SLA and point-in-time/as-of reconstruction are not claimed.
- Shared GitHub-runner timings are diagnostic only. Public operational claims use deterministic rows, partitions, hashes and exact parity.

The progression is:

```text
trust the source
→ define metrics explicitly
→ test decisions without leakage
→ govern schema and metric changes
→ invalidate stale downstream evidence selectively
→ explicitly adopt new semantics when intended
→ selectively rebuild affected evidence
→ correct late-discovered source facts by stable identity
→ supersede published decisions instead of overwriting history
→ require selective replay to equal a clean rebuild
→ validate on external real data
→ update incrementally and recover exactly
→ expose a bounded reporting product
→ evolve its consumer contract without silent migration
→ isolate concurrent consumers without changing the answer
```
