# Late-arrival and watermark governance

v0.26 separates **event time** from **processing time** so a KPI can be evaluated using only data that had actually reached the platform at a reporting snapshot.

## Contract

```text
event_ts     = when the product event happened
ingested_at  = when the analytics platform received it
```

Generated v0.26 data always contains both fields. For backward compatibility, legacy inputs without `ingested_at` are interpreted as immediate arrivals (`ingested_at = event_ts`). If `ingested_at` is explicitly supplied, certification requires it to be parseable and on or after `event_ts`.

The generator uses a dedicated ingestion-delay RNG. Commercial outcomes and product activity therefore do not change when processing-time behaviour is added.

## Reference policy

The current reference uses:

```text
allowed_lateness_hours = 48
processing_as_of       = 2026-04-30 23:59:59.999999 UTC
watermark_event_date   = 2026-04-28
```

An event date on or before the watermark is **nominally final**. A later date is **provisional**.

This is an operating contract, not a guarantee that no older event will ever arrive. A row arriving after nominal finalization is an exception that must be reconciled and backfilled rather than ignored.

## Reference evidence

The deterministic 120-day run contains 275,660 certified events. Of these, 1,367 arrive more than 48 hours after event time, or about **0.496%**.

At the declared processing snapshot, **24 events** for dates already behind the watermark had not yet arrived. Settling those rows later changes **8 product-date-metric cells**:

| Product | Metric | Revised finalized cells | Total revision | Maximum absolute single-cell revision |
|---|---|---:|---:|---:|
| File Transfer | DAU | 2 | +2 users | 1 user |
| Notes App | DAU | 2 | +8 users | 4 users |
| Notes App | Revenue | 1 | +£7.99 | £7.99 |
| Photo Editor | DAU | 2 | +7 users | 4 users |
| Photo Editor | Paid subscriptions | 1 | +1 | 1 |

All other product/metric combinations have zero finalized-cell revision in this snapshot.

The distinction matters: **late row != KPI revision**. A late `app_open` from a user already counted in DAU, for example, may have no aggregate effect.

## Generated evidence

```text
late_arrival_contract.json
late_arrival_summary.csv
watermark_late_events.csv
watermark_metric_revisions.csv
watermark_revision_summary.csv
```

The contract records the policy. The latency summary describes the delay distribution by product/event type. The late-event ledger identifies exceptions. The metric revision report compares the point-in-time snapshot with the settled view.

## Backfill rule

Corrections are keyed by `event_id` and applied idempotently. Reapplying the same correction must be a no-op. This prevents a replayed backfill from duplicating a previously repaired event.

The operating sequence is:

```text
late event detected
      -> preserve row-level exception evidence
      -> recompute affected certified aggregates
      -> compare snapshot and settled values
      -> apply keyed idempotent backfill
      -> record KPI revision
```

## What v0.26 does not claim

The 48-hour watermark is not empirically optimised and the delay distribution is synthetic. The current evidence demonstrates how to measure finalization risk and reconcile exceptions; it does not establish that 48 hours is the correct production SLA for a real company.

A natural next step is to compare several candidate watermarks and select the shortest delay satisfying an explicit revision-risk budget. That decision should use transparent constraints rather than a weighted composite score.
