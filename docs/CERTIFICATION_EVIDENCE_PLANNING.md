# Certification evidence planning

v0.30 answered the question left open by v0.29:

> If no watermark candidate is statistically certified under the declared family-wise rule, which gaps can actually be repaired by more evidence?

v0.31 tightens that answer at the discrete count boundary. A single passing sample size is no longer reported as an evidence target unless the exact upper bound also remains passing across the next full adverse-count jump cycle.

The planning layer separates underlying-risk failures, deterministic hard-gate failures and genuine evidence-depth gaps. It does not treat “collect more data” as a universal remedy.

## Inputs carried forward unchanged

The watermark risk budget remains:

| Constraint | Maximum |
|---|---:|
| Late-event fraction among finalizable events | 0.50% |
| Revised finalized KPI-cell fraction | 1.00% |
| Absolute single-cell revenue revision | £10 |
| Absolute paid-subscription revision | 1 |

The v0.29 simultaneous family is also unchanged:

```text
4 candidates × 9 rolling windows × 2 proportional constraints = 72 bounds
family alpha = 0.05
per-bound alpha = 0.05 / 72
```

There is no weighted score and no post-hoc budget relaxation.

## Planning rule

For each watermark candidate, the planner uses the **worst observed rolling-window proportional rate** as a prospective planning rate.

For a target trial count `n`, the planned number of adverse observations is conservatively rounded upward:

```text
x = ceil(planning_rate × n)
```

The project then evaluates the one-sided exact Clopper–Pearson upper bound at the same per-bound alpha used by v0.29.

This is conditional planning, not a forecast of future certification. It assumes the future risk rate and evidence throughput remain at the stated planning values.

## Why v0.31 changed the target semantics

With `x = ceil(p × n)`, the adverse count changes in discrete jumps. Near a crossing, increasing `n` can therefore produce a small saw-tooth reversal: one sample size passes, then a nearby larger sample size fails when `x` increments.

A single passing `n` is not sufficient evidence for a threshold-style claim. v0.31 reports a target only after auditing the target and the following full count-jump cycle:

```text
cycle_trials = ceil(1 / planning_rate)

candidate target
    ↓
audit target ... target + cycle_trials
    ↓
all positions pass
    ↓
report cycle-stable evidence target
```

This is a local discrete-stability contract. It does **not** claim that every larger possible sample size must pass forever. The machine-readable contract therefore sets:

```text
global_monotonic_threshold_claimed = false
```

## Float boundary contract

The cycle length is part of the statistical contract, so the generator and validator must compute it identically after CSV serialization.

Rates such as `1/135` or `1/333` can round-trip through CSV/pandas so that their reciprocal becomes slightly larger than the mathematical integer. A raw `ceil(1/rate)` would then incorrectly change 135 to 136 or 333 to 334.

v0.31 uses one shared `count_jump_cycle_trials()` implementation. A reciprocal is normalized to its nearest integer only when it lies within **8 floating-point units in the last place (ULPs)** of that integer. Otherwise the conservative `ceil(1/rate)` rule is retained. The reference round-trip cases are 5 ULPs from 135 and 6 ULPs from 333, while a deliberately genuine near-integer reciprocal (`135.00000000001`) remains outside the tolerance and correctly maps to 136.

## When more evidence is not a remedy

A candidate is classified as evidence-depth-only addressable only when all of the following hold:

```text
planning late-event rate            < 0.50%
planning revised-cell rate          < 1.00%
max observed revenue revision       <= £10
max observed paid revision          <= 1
both cycle-stable requirements      are quantifiable inside the search cap
```

If a point risk is already at or above budget, its asymptotic upper bound cannot be pushed below the budget by sample size alone. Likewise, more proportional observations cannot repair a deterministic maximum-revision hard-gate breach.

## v0.31 reference result

The seed-2206, 120-day reference produces:

| Candidate | Main evidence result | Audited cycle | Classification |
|---|---:|---:|---|
| 24h | late 6.9516%, revised cells 1.9400%, max revenue £23.98 | — | structural/hard-gate failure |
| 48h | late target 99,573,018 events; revised cells 1.2882%, max revenue £11.99 | 201 late-event positions | independent rate + hard-gate failures |
| 72h | revised-cell target 14,989; late target beyond 100M cap; max revenue £11.99 | 135 revised-cell positions | hard-gate failure + late search-cap failure |
| 96h | 2,733,153 events and 2,011 KPI cells | 206 late-event / 333 revised-cell positions | **evidence-depth-only** |

The 96-hour candidate remains the only candidate selected by the prospective planning rule.

### 96h cycle-stable evidence requirement

```text
required finalizable-event trials   = 2,733,153
late-event audited cycle            = 206 trial positions
required finalized KPI cells        = 2,011
revised-cell audited cycle           = 333 trial positions
median finalizable-event throughput ~= 2,055.6/day
median KPI-cell throughput           = 9/day
late-event evidence depth            = 1,330 days
revised-cell evidence depth          = 224 days
combined planning depth              = 1,330 days (~3.64 years)
```

The late-event upper bound remains the planning bottleneck.

The change from the v0.30 single-point targets is small in business terms but important in claim semantics:

| Component | v0.30 single passing point | v0.31 cycle-stable target |
|---|---:|---:|
| 48h late events | 99,546,369 | **99,573,018** |
| 72h revised cells | 14,299 | **14,989** |
| 96h late events | 2,718,757 | **2,733,153** |
| 96h revised cells | 1,853 | **2,011** |
| 96h combined evidence depth | 1,323 days | **1,330 days** |

The project does not hide this correction just because the overall operating conclusion stays the same.

## Machine-readable artifacts

The reference build emits:

```text
watermark_evidence_plan.csv
watermark_evidence_plan_contract.json
watermark_evidence_plan_decision.json
```

The plan records candidate-level rates, deterministic gates, exact cycle-stable evidence requirements, audited cycle lengths, throughput, approximate evidence depth, search-cap status and the final `evidence_only_addressable` classification.

The contract records the family alpha, count rule, cycle semantics, search cap, unchanged risk budget and interpretation limits. The decision selects the shortest candidate whose current gap is evidence-depth-only.

## CI contract

`validate_evidence_plan.py` checks the candidate set, component accounting, search-cap consistency, cycle lengths, positive throughput, unchanged hard constraints and shortest eligible-candidate selection. It imports the same count-jump-cycle function used by the generator, so serialization cannot silently create a second statistical definition.

`validate_reference_claims.py` separately pins the deterministic v0.31 values, including the 96h cycle-stable targets and audited cycle lengths. A changed statistical boundary therefore has to be reviewed and updated explicitly before CI becomes green.

## Interpretation boundary

The planning calculation is not a production SLA recommendation and is not a guarantee of certification after a specified number of days. It assumes:

- future risk rates remain at the declared worst observed planning rates;
- evidence throughput remains comparable;
- the binomial/Bernoulli interpretation used by the Clopper–Pearson layer remains appropriate;
- the candidate set and risk budget remain pre-specified.

Batch-, source- and day-level dependence is still outside the current binomial certification model. A later cluster-aware analysis may change the evidence requirement, but it must be specified on statistical grounds rather than selected to obtain a desired SLA.
