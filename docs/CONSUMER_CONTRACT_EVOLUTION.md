# Consumer contract evolution

v0.39 adds governed evolution to the reporting data product introduced in v0.38. The goal is not to add a web framework or another transport. The goal is to prove that a reporting interface can change without silently breaking existing consumers.

## Published schemas

The JSON response family is `retail-daily-metrics`.

- **schema 1.0** remains the default. Existing callers that do not request a schema version continue to receive the original top-level response shape.
- **schema 1.1** is opt-in. It adds one top-level `contract` object containing the schema family, negotiated version, explicit backward-compatibility path and a deterministic SHA-256 of the metric catalog.

The data-product release is v0.39.0, but the default consumer schema remains 1.0. These are intentionally separate version axes.

## No silent migration

A caller must explicitly request schema 1.1. The default is still 1.0:

```bash
python scripts/query_retail_metrics.py \
  --incremental-dir build/incremental-retail \
  --start 2010-12-01 \
  --end 2010-12-07 \
  --metrics revenue_gbp,orders,active_customers \
  --format json
```

Opt in to the additive schema:

```bash
python scripts/query_retail_metrics.py \
  --incremental-dir build/incremental-retail \
  --start 2010-12-01 \
  --end 2010-12-07 \
  --metrics revenue_gbp,orders,active_customers \
  --format json \
  --schema-version 1.1
```

CSV remains the stable date/metric row projection. Schema negotiation governs the JSON envelope.

## Governed migration examples

v0.39 evaluates three concrete consumer-facing proposals against schema 1.0:

| Proposal | Classification | Decision | Why |
|---|---|---|---|
| add `contract` metadata | ADDITIVE | APPROVE | Existing consumers stay on negotiated 1.0; 1.1 is explicit opt-in. |
| rename `row_count` to `rows` | BREAKING | WITHHOLD | A published top-level field disappears. |
| change `orders` from integer to float | BREAKING | WITHHOLD | Published metric type semantics change. |

The classifier works at field level across the top-level envelope, query, availability, partition provenance, data-row base fields and metric types. A removal, rename or type change is non-compensatory: an otherwise useful migration is still withheld if it breaks the existing contract.

## Real-data compatibility evidence

The v0.39 operational workflow builds the same validated UCI Online Retail II metric store used by v0.37/v0.38, then executes the same seven-day December 2010 query through both schemas.

The required evidence is:

- the unversioned/default call still returns schema 1.0;
- explicit schema 1.1 negotiation succeeds;
- query payloads are identical across 1.0 and 1.1;
- returned metric rows are identical across 1.0 and 1.1;
- the stable query/data response SHA-256 is identical across 1.0 and 1.1;
- deterministic work selection is identical across 1.0 and 1.1;
- schema 1.1 exposes the metric-catalog digest;
- an unsupported schema version is rejected;
- the independent validator recomputes all three migration classifications from the serialized candidate schemas rather than trusting the production classifier.

The compatibility layer does not reparse the source XLSX and does not redefine any metric. It governs the consumer boundary over already validated metric partitions.

## Claim boundary

`ADDITIVE` does not mean every imaginable client can consume the newer schema without change. A client that rejects all unknown JSON fields may reject any additive field. The guarantee here is stronger and more explicit: strict existing consumers can continue to negotiate schema 1.0, while consumers that opt in to 1.1 receive the additive contract metadata.

No deprecation date or production support lifetime is claimed. The repository demonstrates the mechanism and evidence gates, not an organisational SLA.
