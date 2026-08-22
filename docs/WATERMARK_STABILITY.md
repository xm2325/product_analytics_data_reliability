# Rolling watermark stability

v0.28 asks whether a watermark selected from one processing snapshot remains acceptable when the reporting date moves through time. v0.29 keeps that descriptive backtest intact and adds a separate statistical certification layer.

## Why this exists

A single end-of-period snapshot can make a finalization SLA look safer than it was earlier in the operating history. The ingestion-delay distribution is stochastic, metric revisions are sparse, and the maximum observed revision can be driven by a small number of exceptions.

The rolling backtest therefore replays the unchanged 24/48/72/96-hour candidate grid through nine weekly `processing_as_of` snapshots.

## Non-negotiable decision rules

A candidate is point-estimate feasible in a window only if all of the following pass:

```text
late-event fraction <= 0.50%
revised KPI-cell fraction <= 1.00%
max |revenue revision| <= £10
max |paid-subscription revision| <= 1
```

A candidate is called **observed stable** only if it is feasible in every declared window. The observed-stability policy is the shortest such candidate. The budget is frozen before inspecting the rolling outcome.

## Reference windows and observed result

```text
2026-03-05
2026-03-12
2026-03-19
2026-03-26
2026-04-02
2026-04-09
2026-04-16
2026-04-23
2026-04-30
```

Per-window shortest feasible policies:

```text
72h, 72h, 72h, 96h, 48h, 48h, 48h, 48h, 48h
```

| Candidate | Feasible windows | Selected windows | Feasibility rate | Observed stable? |
|---|---:|---:|---:|---|
| 24h | 0 | 0 | 0.0% | No |
| 48h | 5 | 5 | 55.6% | No |
| 72h | 8 | 3 | 88.9% | No |
| 96h | 9 | 1 | 100% | Yes |

The point-estimate observed-stability result is therefore:

```text
selected observed-stable SLA = 96h
```

This remains a valid descriptive statement in v0.29.

## v0.29: observed stable does not mean certified

v0.29 adds one-sided simultaneous upper confidence bounds to the two proportional constraints. The full policy-selection family contains 72 bounds: four candidates × nine windows × two proportions. A 95% family-wise Bonferroni correction is applied.

The result is stricter than the point-estimate backtest:

| Candidate | Observed feasible windows | Statistically certified windows |
|---|---:|---:|
| 24h | 0 / 9 | 0 / 9 |
| 48h | 5 / 9 | 0 / 9 |
| 72h | 8 / 9 | 0 / 9 |
| 96h | **9 / 9** | **0 / 9** |

For 96h, the worst observed late-event fraction is 0.4864%, but the worst simultaneous upper bound is about **0.5485%**, above the 0.50% budget. Its worst observed revised-cell fraction is 0.3003%, while the worst simultaneous upper bound is about **1.7385%**, above the 1.00% budget.

Therefore the current evidence hierarchy is:

```text
48h = Apr-30 local point-estimate optimum
96h = observed rolling-stable policy
none = statistically certified family-wise 95% policy under v0.29
```

The project does not reinterpret the uncertified result as evidence that 96h is unsafe. It says the present evidence is insufficient for the stronger certification claim.

## Why the negative result is retained

The v0.29 method does not react by lowering the confidence level, shrinking the multiple-comparison family or loosening the risk budget. Those choices would be post-hoc responses to an inconvenient result.

Instead, `watermark_stability_decision.json` continues to preserve the descriptive v0.28 decision, while `watermark_certification_decision.json` separately reports `no_candidate_certified_familywise_95`.

See [`WATERMARK_UNCERTAINTY.md`](WATERMARK_UNCERTAINTY.md) for the statistical contract and model boundary.
