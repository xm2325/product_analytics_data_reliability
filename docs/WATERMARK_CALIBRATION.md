# Watermark SLA calibration and stability

The current workflow separates three questions that should not be conflated:

1. **Point-in-time calibration:** what is the shortest candidate satisfying every hard risk constraint at one declared processing snapshot?
2. **Observed rolling stability:** what is the shortest candidate satisfying those constraints across every declared historical snapshot?
3. **Uncertainty-aware certification:** after accounting for simultaneous estimation uncertainty across candidate-window proportional constraints, can any candidate be certified against the same budget?

For the deterministic reference the answers are **48h**, **96h**, and **no certified candidate**, respectively.

## Reference contract

```text
seed = 2206
days = 120
final processing_as_of = 2026-04-30 23:59:59.999999 UTC
candidate lateness = {24h, 48h, 72h, 96h}
rolling snapshots = 9 weekly windows from 2026-03-05 to 2026-04-30
```

The risk budget is unchanged:

| Constraint | Maximum allowed |
|---|---:|
| Late events among finalizable historical events | **0.50%** |
| Revised finalized KPI cells | **1.00%** |
| Absolute single-cell revenue revision | **£10.00** |
| Absolute single-cell paid-subscription revision | **1** |

These thresholds are explicit scenario-management inputs for the synthetic portfolio, not estimates of a real company's tolerance.

## Point-in-time denominator and Apr-30 result

For a candidate watermark, the late-event fraction is calculated only from events whose `event_date` is on or before that candidate's watermark date. Future/provisional event dates cannot influence the current decision denominator.

At 2026-04-30:

| Candidate | Finalizable events | Point-in-time late fraction | Revised-cell fraction | Max revenue revision | Feasible? |
|---|---:|---:|---:|---:|---|
| 24h | 251,928 | **6.932%** | **1.214%** | £9.99 | No |
| 48h | 249,634 | **0.4951%** | **0.753%** | £7.99 | Yes |
| 72h | 247,364 | **0.4944%** | **0.380%** | £0.00 | Yes |
| 96h | 245,130 | **0.4814%** | **0.000%** | £0.00 | Yes |

The point-in-time rule is:

```text
minimize finalization lag
subject to every hard risk constraint passing
```

so the final snapshot selects **48h**.

## Observed rolling stability

The same candidate grid and unchanged budget are replayed through nine weekly snapshots. Per-window shortest-feasible policies are:

```text
72h, 72h, 72h, 96h, 48h, 48h, 48h, 48h, 48h
```

| Candidate | Feasible windows | Feasibility rate | Worst revised-cell fraction | Worst revenue revision | Stable all windows? |
|---|---:|---:|---:|---:|---|
| 24h | 0 / 9 | 0.0% | 1.940% | £23.98 | No |
| 48h | 5 / 9 | 55.6% | 1.288% | £11.99 | No |
| 72h | 8 / 9 | 88.9% | 0.741% | £11.99 | No |
| 96h | **9 / 9** | **100%** | 0.300% | £0.00 | **Yes** |

The observed all-window rule therefore selects **96h**. The project does not relax the all-window rule to 8/9 to preserve a 72-hour answer, and it does not raise the £10 budget after observing the £11.99 breach.

## v0.29 uncertainty-aware certification

v0.29 retains the point-estimate results above and adds a separate certification question. It computes one-sided exact Clopper–Pearson upper bounds for the late-event and revised-cell proportions, then applies a 95% family-wise Bonferroni correction over the entire selection family:

```text
4 candidates × 9 windows × 2 proportional constraints = 72 bounds
per-bound alpha = 0.05 / 72 = 0.0006944444...
```

The maximum revenue and paid-subscription revisions remain deterministic hard gates; no confidence interval is invented for maxima without a defensible tail model.

Under this stronger rule, every candidate has **0/9 certified windows**. In particular, 96h remains observed feasible in 9/9 windows but its worst simultaneous upper bounds are approximately 0.5485% for late events and 1.7385% for revised cells, above the 0.50% and 1.00% budgets.

Therefore:

```text
point-in-time selected watermark = 48h
observed stable watermark        = 96h
family-wise 95% certified SLA    = none
```

This is an evidence-strength distinction, not a contradiction. See [`WATERMARK_UNCERTAINTY.md`](WATERMARK_UNCERTAINTY.md) for the full statistical contract and limitations.

## Evidence artifacts

```text
watermark_policy_grid.csv
watermark_policy_decision.json
watermark_rolling_grid.csv
watermark_rolling_windows.csv
watermark_stability_summary.csv
watermark_stability_decision.json
watermark_uncertainty_grid.csv
watermark_uncertainty_summary.csv
watermark_uncertainty_contract.json
watermark_certification_decision.json
```

The repository deliberately keeps local feasibility, observed stability and statistical certification in separate artifacts so one cannot silently overwrite another.
