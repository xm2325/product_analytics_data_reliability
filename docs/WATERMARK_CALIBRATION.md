# Watermark SLA calibration and stability

v0.28 separates two questions that should not be conflated:

1. **Point-in-time calibration:** what is the shortest candidate satisfying every hard risk constraint at one declared processing snapshot?
2. **Rolling stability:** what is the shortest candidate satisfying the same constraints across every declared historical snapshot?

The second is the stronger SLA claim.

## Reference contract

```text
seed = 2206
days = 120
final processing_as_of = 2026-04-30 23:59:59.999999 UTC
candidate lateness = {24h, 48h, 72h, 96h}
rolling snapshots = 9 weekly windows from 2026-03-05 to 2026-04-30
```

The risk budget is unchanged from v0.27:

| Constraint | Maximum allowed |
|---|---:|
| Late events among finalizable historical events | **0.50%** |
| Revised finalized KPI cells | **1.00%** |
| Absolute single-cell revenue revision | **£10.00** |
| Absolute single-cell paid-subscription revision | **1** |

These thresholds are explicit scenario-management inputs for the synthetic portfolio. They are not estimates of a real company's tolerance.

## Point-in-time denominator

v0.28 corrects the SLA decision scope. For a candidate watermark, the late-event fraction is calculated only from events whose `event_date` is on or before that candidate's watermark date.

```text
processing_as_of
      |
      +--> candidate lateness
              |
              v
      watermark_event_date
              |
              v
 event_date <= watermark
              |
              +--> finalizable_events
              `--> late-event risk denominator
```

Rows whose event date occurs after the candidate watermark are future/provisional with respect to that decision and cannot affect the policy denominator. A whole-settled-stream late fraction remains available as a diagnostic, but it is not the hard constraint.

## Final-snapshot candidate replay

At 2026-04-30:

| Candidate | Finalizable events | Point-in-time late fraction | Missing after nominal finalization | Revised KPI cells | Revised-cell fraction | Max revenue revision | Max paid revision | Feasible? |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| 24h | 251,928 | **6.932%** | 62 | 13 / 1,071 | **1.214%** | £9.99 | 1 | **No** |
| 48h | 249,634 | **0.4951%** | 24 | 8 / 1,062 | **0.753%** | £7.99 | 1 | **Yes** |
| 72h | 247,364 | **0.4944%** | 11 | 4 / 1,053 | **0.380%** | £0.00 | 1 | **Yes** |
| 96h | 245,130 | **0.4814%** | 0 | 0 / 1,044 | **0.000%** | £0.00 | 0 | **Yes** |

The point-in-time selector remains:

```text
minimize finalization lag
subject to every hard risk constraint passing
```

Therefore the Apr-30 snapshot still selects **48 hours**.

## Rolling backtest

The single-snapshot result is then replayed through nine weekly processing snapshots. Every window uses exactly the same candidate grid and risk budget. No threshold is refitted after viewing the result.

Per-window shortest feasible policy:

```text
2026-03-05 -> 72h
2026-03-12 -> 72h
2026-03-19 -> 72h
2026-03-26 -> 96h
2026-04-02 -> 48h
2026-04-09 -> 48h
2026-04-16 -> 48h
2026-04-23 -> 48h
2026-04-30 -> 48h
```

Candidate stability summary:

| Candidate | Feasible windows | Feasibility rate | Mean late fraction | Worst late fraction | Worst revised-cell fraction | Worst revenue revision | Stable all windows? |
|---|---:|---:|---:|---:|---:|---:|---|
| 24h | 0 / 9 | 0.0% | 6.931% | 6.952% | 1.940% | £23.98 | No |
| 48h | 5 / 9 | 55.6% | 0.4946% | 0.4977% | 1.288% | £11.99 | No |
| 72h | 8 / 9 | 88.9% | 0.4945% | 0.4999% | 0.741% | £11.99 | No |
| 96h | **9 / 9** | **100%** | 0.4814% | 0.4864% | 0.300% | £0.00 | **Yes** |

## Stable SLA decision

The v0.28 operating rule is deliberately strict:

```text
minimize finalization lag
subject to every original hard constraint passing in every rolling backtest window
```

This selects:

```text
selected_lateness_hours = 96
selected_feasibility_rate = 1.0
weighted_score_used = false
budget_relaxed_after_backtest = false
```

The result is intentionally allowed to contradict the final-snapshot recommendation. 48h remains a valid description of the Apr-30 local optimum; it is not stable enough to be promoted to the stronger cross-window SLA claim.

## Why not choose 72h at 8/9?

Because the stability rule was declared as all-window feasibility. Relaxing the rule after observing that 72h misses one window would turn the backtest into a post-hoc justification exercise.

The 72-hour candidate's failure is also operationally interpretable: its worst observed single-cell revenue revision is **£11.99**, above the unchanged £10 limit. The project preserves that negative result instead of moving the threshold to fit it.

## Evidence artifacts

Point-in-time:

```text
watermark_policy_grid.csv
watermark_policy_decision.json
```

Rolling:

```text
watermark_rolling_grid.csv
watermark_rolling_windows.csv
watermark_stability_summary.csv
watermark_stability_decision.json
```

The rolling grid contains every window × candidate result, not only the selected policies. This makes constraint failures inspectable rather than reducing the result to a single recommendation.

## Validation contract

The repository uses three independent validation layers beyond unit tests:

- `validate_build.py` checks generic reference-build invariants;
- `validate_watermark_backtest.py` checks point-in-time scope, per-window shortest-feasible selection, stability accounting, no weighted score and no post-backtest budget relaxation;
- `validate_reference_claims.py` pins the deterministic public reference: final snapshot selects 48h, rolling feasibility counts are 0/9, 5/9, 8/9, 9/9, and the stable SLA is 96h.

A future change may legitimately alter those numbers, but then the pinned claim gate fails and the public documentation must be reviewed explicitly.

## Limitations

The ingestion-delay model and risk thresholds are synthetic. Nine windows are a robustness check, not proof that 96h is universally correct. The rolling windows also share one simulated data-generating process and therefore are not independent replications.

The next methodological step is uncertainty-aware certification: quantify uncertainty around the observed late-event/revision risks rather than treating each backtest proportion as known exactly. That extension should preserve the same non-compensatory constraints and should be allowed to return **no certified SLA** if the evidence is insufficient.
