# Watermark SLA calibration

v0.27 answers a narrower question than the v0.26 late-arrival audit:

> Given an explicit revision-risk budget, how long should the metric layer wait before calling an event date final?

The answer is not chosen from a weighted score. Each candidate must satisfy every declared constraint in its natural unit, and the selected policy is the **shortest feasible candidate**.

## Reference decision contract

The deterministic reference run uses the same certified event stream and processing snapshot for every candidate:

```text
seed = 2206
days = 120
processing_as_of = 2026-04-30 23:59:59.999999 UTC
candidate lateness = {24h, 48h, 72h, 96h}
```

The reference risk budget is:

| Constraint | Maximum allowed |
|---|---:|
| Events arriving beyond candidate watermark | **0.50%** of certified events |
| Revised finalized KPI cells | **1.00%** of finalized product-date-metric cells |
| Absolute single-cell revenue revision | **£10.00** |
| Absolute single-cell paid-subscription revision | **1** subscription |

These are transparent scenario thresholds for this portfolio demonstration. They are not claimed as universal production tolerances.

## Verified candidate replay

| Candidate | Finalization lag | Late-event fraction | Events missing after nominal finalization | Revised KPI cells | Revised-cell fraction | Max revenue revision | Max paid revision | Feasible? |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| 24h | 1 day | **6.958%** | 62 | 13 / 1,071 | **1.214%** | £9.99 | 1 | **No** |
| 48h | 2 days | **0.496%** | 24 | 8 / 1,062 | **0.753%** | £7.99 | 1 | **Yes** |
| 72h | 3 days | **0.496%** | 11 | 4 / 1,053 | **0.380%** | £0.00 | 1 | **Yes** |
| 96h | 4 days | **0.482%** | 0 | 0 / 1,044 | **0.000%** | £0.00 | 0 | **Yes** |

The 24-hour policy fails two independent constraints: the late-event fraction and the revised-KPI-cell fraction. The 48-hour policy is the first candidate to satisfy all four constraints. The 72-hour and 96-hour policies reduce exception/revision risk further, but they require one or two additional days before a date can be served as final.

The selected reference policy is therefore:

```text
selected_lateness_hours = 48
selection_rule = shortest candidate satisfying every hard risk constraint
weighted_score_used = false
```

## Why 48h rather than 72h or 96h?

The objective is not to minimize revision risk regardless of latency. If that were the rule, the longest available watermark would mechanically win.

The operating question is instead constrained optimization:

```text
minimize finalization lag
subject to:
    late-event fraction <= 0.50%
    revised KPI-cell fraction <= 1.00%
    max |revenue revision| <= £10
    max |paid-subscription revision| <= 1
```

Under the pinned reference evidence, 48 hours is the minimum candidate that enters the feasible region. This preserves more freshness than 72/96 hours without violating the declared risk budget.

## Why keep event-level and KPI-level risk separate?

A late row does not automatically revise a metric. For example, another `app_open` from a user already counted in that day's distinct-user DAU may arrive late but leave DAU unchanged.

For that reason the policy grid reports both:

```text
late_event_fraction
revised_metric_cell_fraction
```

The first measures pipeline lateness. The second measures whether the lateness changes a served analytical result. Neither is substituted for the other.

## Evidence and CI contract

The generated artifacts are:

```text
watermark_policy_grid.csv
watermark_policy_decision.json
```

`watermark_policy_grid.csv` keeps every candidate and every individual pass/fail flag. `watermark_policy_decision.json` records the budget, selection rule, candidate set, selected SLA and selected-row evidence.

The generic build validator checks that the selector always chooses the shortest feasible row and never uses a weighted score. A second pinned-reference validator checks the published deterministic claim itself:

```text
24h must remain infeasible
24h must fail late-event and revised-cell fraction gates
48h must remain feasible
selected SLA must remain 48h
```

If a later code, metric or synthetic-data change moves that boundary, CI should fail so the public result is reviewed rather than silently drifting.

## Relationship to v0.26

v0.26 established the processing-time primitives: `event_ts`, `ingested_at`, the row-level late-event ledger, point-in-time snapshots, metric revision reconciliation and idempotent backfill.

v0.27 does not replace that audit trail. It consumes the same primitives to compare several finalization policies. See [`LATE_ARRIVAL_GOVERNANCE.md`](LATE_ARRIVAL_GOVERNANCE.md) for the lower-level exception/backfill path.

## Limitations

This remains a synthetic reference study. The risk budget is explicit but externally chosen; the ingestion-delay distribution is simulated; the candidate grid is discrete; and the current decision is based on one reporting snapshot.

A production policy should be recalibrated over many historical processing snapshots and should only be segmented by source/event type when there is enough stable evidence to justify different SLAs. A useful next robustness test is therefore a **rolling watermark backtest**: ask whether 48 hours remains the shortest feasible policy across multiple as-of dates rather than only on 2026-04-30.
