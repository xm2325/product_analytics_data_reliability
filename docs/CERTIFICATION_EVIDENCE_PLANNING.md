# Certification evidence planning

v0.30 answers the question left open by v0.29:

> If no watermark candidate is statistically certified under the declared family-wise rule, which gaps can actually be repaired by more evidence?

The answer is **not** “collect more data for every candidate”. The planning layer first separates underlying-risk failures, deterministic hard-gate failures and genuine evidence-depth gaps.

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

For each watermark candidate, v0.30 uses the **worst observed rolling-window proportional rate** as a prospective planning rate.

For a target trial count `n`, the planned number of adverse observations is conservatively rounded upward:

```text
x = ceil(planning_rate × n)
```

The project then searches for an evidence size whose one-sided exact Clopper–Pearson upper bound satisfies the original proportional budget at the same per-bound alpha used by v0.29.

This is conditional planning, not a forecast of future certification. It assumes the future risk rate and evidence throughput remain at the stated planning values.

## When more evidence is not a remedy

A candidate is classified as evidence-depth-only addressable only when all of the following hold:

```text
planning late-event rate            < 0.50%
planning revised-cell rate          < 1.00%
max observed revenue revision       <= £10
max observed paid revision          <= 1
both exact evidence requirements    are quantifiable inside the search cap
```

If a point risk is already at or above budget, its asymptotic upper bound cannot be pushed below the budget by sample size alone. Likewise, more proportional observations cannot repair a deterministic maximum-revision hard-gate breach.

## Reference result

The seed-2206, 120-day reference produces:

| Candidate | Late planning rate | Revised-cell planning rate | Max revenue revision | Classification |
|---|---:|---:|---:|---|
| 24h | 6.9516% | 1.9400% | £23.98 | structural/hard-gate failure |
| 48h | 0.4977% | 1.2882% | £11.99 | independent rate + hard-gate failures |
| 72h | 0.4999% | 0.7407% | £11.99 | hard-gate failure; late requirement beyond search cap |
| 96h | 0.4864% | 0.3003% | £0.00 | **evidence-depth-only** |

The 96-hour candidate is therefore the only candidate selected by the prospective planning rule.

### 96h evidence requirement

```text
required finalizable-event trials  = 2,718,757
required finalized KPI cells       = 1,853
median finalizable-event throughput ~= 2,055.6/day
median KPI-cell throughput          = 9/day
late-event evidence depth           = 1,323 days
revised-cell evidence depth         = 206 days
combined planning depth             = 1,323 days (~3.62 years)
```

The late-event upper bound is the bottleneck.

This is intentionally a **negative operational result**. Under the current synthetic rates and very conservative 95% family-wise certification rule, passively accumulating evidence for roughly 3.6 years is not an attractive strategy. The planning layer exposes that problem rather than hiding it by relaxing alpha or the risk budget.

## Why 48h and 72h are not sample-size problems

For 48h, the late-event rate is just below the proportional budget, but:

```text
worst revised-cell rate = 1.2882% > 1.00%
max revenue revision    = £11.99  > £10
```

Even the late-event proportion alone would require roughly 99.55 million finalizable events under the planning rule. But that number is not presented as a remedy because other constraints already fail.

For 72h:

```text
max revenue revision = £11.99 > £10
```

and the late-event evidence requirement is above the declared 100,000,000-trial search cap. The revised-cell proportion alone needs about 14,299 cells, or roughly 1,589 days at nine finalized KPI cells per day, but satisfying that one component would still not repair the candidate.

## Machine-readable artifacts

The reference build emits:

```text
watermark_evidence_plan.csv
watermark_evidence_plan_contract.json
watermark_evidence_plan_decision.json
```

The plan records candidate-level rates, deterministic gates, exact evidence requirements, throughput, approximate evidence depth, search-cap status and the final `evidence_only_addressable` classification.

The contract records the family alpha, count rule, search cap, unchanged risk budget and interpretation limits. The decision selects the shortest candidate whose current gap is evidence-depth-only.

## CI contract

`validate_evidence_plan.py` checks:

- the candidate set and required fields;
- component accounting for `evidence_only_addressable`;
- exact-evidence quantification and search-cap consistency;
- no sample plan for a proportional rate already at/above budget;
- positive evidence throughput;
- no weighted score;
- no budget relaxation;
- shortest eligible-candidate selection.

`validate_reference_claims.py` separately pins the deterministic v0.30 reference values so public numerical claims cannot silently drift.

## Interpretation boundary

The planning calculation is not a production SLA recommendation and is not a guarantee of certification after a specified number of days. It assumes:

- future risk rates remain at the declared worst observed planning rates;
- evidence throughput remains comparable;
- the binomial/Bernoulli interpretation used by the Clopper–Pearson layer remains appropriate;
- the candidate set and risk budget remain pre-specified.

Batch-, source- and day-level dependence is still outside the current binomial certification model. A later cluster-aware analysis is allowed to increase or decrease the evidence requirement; it must not be tuned merely to obtain a desired SLA.
