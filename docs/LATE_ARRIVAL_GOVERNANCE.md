# Late-arrival and watermark governance

v0.26 separates **event time** from **processing time** so a KPI can be evaluated using only data that had actually reached the platform at a reporting snapshot. v0.27 added point-in-time SLA calibration; v0.28 keeps the audit layer separate and adds a rolling stability decision on top.

## Contract

```text
event_ts     = when the product event happened
ingested_at  = when the analytics platform received it
```

Generated v0.26+ data contains both fields. For backward compatibility, legacy inputs without `ingested_at` are interpreted as immediate arrivals (`ingested_at = event_ts`). If `ingested_at` is explicitly supplied, certification requires it to be parseable and on or after `event_ts`.

The generator uses a dedicated ingestion-delay RNG. Commercial outcomes and product activity therefore do not change when processing-time behaviour is added.

## Reference audit policy

The row-level audit remains pinned at:

```text
allowed_lateness_hours = 48
processing_as_of       = 2026-04-30 23:59:59.999999 UTC
watermark_event_date   = 2026-04-28
```

An event date on or before the watermark is **nominally final**. A later date is **provisional**.

This audit setting is not the same thing as the current stable operating recommendation. It is retained so the row-level v0.26 exception evidence remains reproducible.

## Reference evidence

The deterministic 120-day run contains 275,660 certified events. Of these, 1,367 arrive more than 48 hours after event time, or about **0.496%** of the full settled stream.

At the declared processing snapshot, **24 events** for dates already behind the 48-hour watermark had not yet arrived. Settling those rows later changes **8 product-date-metric cells**:

| Product | Metric | Revised finalized cells | Total revision | Maximum absolute single-cell revision |
|---|---|---:|---:|---:|
| File Transfer | DAU | 2 | +2 users | 1 user |
| Notes App | DAU | 2 | +8 users | 4 users |
| Notes App | Revenue | 1 | +£7.99 | £7.99 |
| Photo Editor | DAU | 2 | +7 users | 4 users |
| Photo Editor | Paid subscriptions | 1 | +1 | 1 |

All other product/metric combinations have zero finalized-cell revision in this snapshot.

The distinction matters: **late row != KPI revision**. A late `app_open` from a user already counted in DAU, for example, may have no aggregate effect.

## Generated audit evidence

```text
late_arrival_contract.json
late_arrival_summary.csv
watermark_late_events.csv
watermark_metric_revisions.csv
watermark_revision_summary.csv
```

The contract records the audit policy. The latency summary describes the delay distribution by product/event type. The late-event ledger identifies exceptions. The metric revision report compares the point-in-time snapshot with the settled view.

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

## v0.28: audit, local calibration and stable SLA are separate layers

The repository now exposes three distinct freshness concepts:

```text
48h audit policy
    = retained row-level exception/backfill reference

48h Apr-30 point-in-time selection
    = shortest candidate satisfying all hard constraints at that snapshot

96h rolling stable selection
    = shortest candidate satisfying the same hard constraints in all 9 backtest windows
```

The v0.28 decision denominator is also stricter than the original audit summary: only events whose `event_date` is on or before a candidate watermark enter that candidate's SLA late-event fraction. Future/provisional event dates do not participate in the current decision.

Across nine weekly snapshots, 48h is feasible in 5/9 windows, 72h in 8/9, and 96h in 9/9. The budget is not relaxed after observing the backtest, so the current synthetic-reference stable SLA is **96 hours**.

This still does not establish a universal production SLA. The delay process and thresholds are synthetic, and observed 9/9 feasibility is not yet a statistical confidence statement. See [`WATERMARK_CALIBRATION.md`](WATERMARK_CALIBRATION.md) and [`WATERMARK_STABILITY.md`](WATERMARK_STABILITY.md).
