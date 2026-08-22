# Rolling watermark stability

v0.28 asks whether a watermark selected from one processing snapshot remains acceptable when the reporting date moves through time.

## Why this exists

A single end-of-period snapshot can make a finalization SLA look safer than it was earlier in the operating history. The ingestion-delay distribution is stochastic, metric revisions are sparse, and the maximum observed revision can be driven by a small number of exceptions.

The rolling backtest therefore replays the unchanged 24/48/72/96-hour candidate grid through nine weekly `processing_as_of` snapshots.

## Non-negotiable decision rules

The backtest does not introduce a weighted objective. A candidate is feasible in a window only if all of the following pass:

```text
late-event fraction <= 0.50%
revised KPI-cell fraction <= 1.00%
max |revenue revision| <= £10
max |paid-subscription revision| <= 1
```

A candidate is called **stable** only if it is feasible in every declared window. The stable SLA is the shortest stable candidate.

The budget is frozen before inspecting the rolling outcome.

## Reference windows

The deterministic reference evaluates:

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

The per-window shortest feasible policies are:

```text
72h, 72h, 72h, 96h, 48h, 48h, 48h, 48h, 48h
```

This sequence is itself useful evidence: the final five snapshots would make a 48-hour policy look consistently acceptable, but earlier windows show that conclusion is not stable over the full declared period.

## Candidate stability

| Candidate | Feasible windows | Selected windows | Feasibility rate | Stable? |
|---|---:|---:|---:|---|
| 24h | 0 | 0 | 0.0% | No |
| 48h | 5 | 5 | 55.6% | No |
| 72h | 8 | 3 | 88.9% | No |
| 96h | 9 | 1 | 100% | Yes |

The difference between `feasible_windows` and `selected_windows` is intentional. A candidate may satisfy every constraint in a window but still not be selected because a shorter candidate is also feasible.

## Failure modes by candidate

**24h** is structurally too aggressive for this synthetic delay process. It fails all nine windows and reaches a worst late-event rate of about 6.95%, a worst revised-cell fraction of 1.94%, and a worst revenue revision of £23.98.

**48h** looks good at Apr-30 but fails four of nine windows. Across the rolling period its worst revised-cell fraction is 1.288% and its worst revenue revision is £11.99, crossing two different hard constraints.

**72h** is much more stable, passing eight of nine windows. Its remaining failure is still real: the maximum observed revenue revision is £11.99, above the unchanged £10 budget.

**96h** passes all nine windows. Its worst revised-cell fraction is about 0.300% and no revenue or paid-subscription revision breaches are observed in the declared backtest.

## Decision

```text
selected stable SLA = 96h
```

This is not a claim that four days is universally optimal. It means that, among the four predeclared candidates and under the predeclared synthetic risk budget, 96h is the shortest candidate with 9/9 historical feasibility in this reference study.

## Important boundary

The rolling backtest is evidence about **observed stability**, not statistical certainty. It does not yet account for binomial/proportion uncertainty, sparse-tail uncertainty, or uncertainty in the maximum-revision metrics.

For that reason v0.28 does not use language such as “95% certain that 96h is safe.” The next release should add an explicit uncertainty-aware certification layer and be willing to return `insufficient_evidence` or `no_candidate_certified` rather than converting a point estimate into an unwarranted probability statement.
