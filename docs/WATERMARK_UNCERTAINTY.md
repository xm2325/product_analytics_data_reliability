# Uncertainty-aware watermark certification

v0.29 closes a limitation left deliberately open by v0.28.

v0.28 established that 96 hours was **observed feasible in all nine rolling backtest windows**. That is a stability statement about point estimates. It is not, by itself, a statistical confidence statement about the underlying late-event or KPI-revision rates.

v0.29 therefore asks:

> After accounting for estimation uncertainty and the fact that policy selection inspects many candidate-window constraints, can any candidate be certified against the same risk budget?

The reference answer is **no**.

## Risk budget

The existing non-compensatory budget is unchanged:

| Constraint | Limit |
|---|---:|
| Late-event proportion among candidate-finalizable events | 0.50% |
| Revised finalized KPI-cell proportion | 1.00% |
| Maximum absolute single-cell revenue revision | £10 |
| Maximum absolute paid-subscription revision | 1 |

No threshold is fitted to the observed v0.29 result.

## Statistical family

There are:

```text
4 watermark candidates
× 9 rolling snapshots
× 2 proportional constraints
= 72 one-sided bounds
```

The family-wise error rate is fixed at 5%. Bonferroni therefore assigns:

```text
alpha_family = 0.05
alpha_each   = 0.05 / 72
             = 0.0006944444444444445
```

Each proportion receives a one-sided exact Clopper–Pearson upper bound.

For `x` observed events in `n` trials, with per-bound significance level `alpha_each`, the upper bound is the appropriate beta quantile:

```text
U = BetaQuantile(1 - alpha_each; x + 1, n - x)
```

with the all-success edge case set to one.

The certification question is one-sided because the operating concern is whether true risk may be **above** a declared maximum tolerance.

## Why correct over all candidates and windows?

The eventual policy is selected after examining all candidate-window results. Treating only the final selected candidate as if it had been pre-specified would ignore the selection process.

The Bonferroni family therefore includes every proportional constraint used by selection. This is conservative but transparent.

Overlapping rolling windows do not invalidate the Bonferroni family-wise inequality because that correction does not require independence across tests. However, the individual exact-binomial bounds still rely on a Bernoulli/binomial interpretation of the observations inside each proportion. Day-, source-, batch- or user-level dependence is not modelled in v0.29.

## Why the maximum-revision constraints do not get confidence intervals

The maximum revenue and paid-subscription revisions are sparse extreme-value statistics. Their uncertainty depends on a tail model or an appropriate resampling design.

v0.29 does not fabricate such a model simply to make all four constraints look statistically symmetrical. Instead:

```text
late-event proportion      -> simultaneous one-sided exact upper bound
revised-cell proportion    -> simultaneous one-sided exact upper bound
max revenue revision       -> deterministic observed hard gate
max paid revision          -> deterministic observed hard gate
```

This limitation is explicit in `watermark_uncertainty_contract.json`.

## Reference result

| Candidate | Observed feasible windows | Certified windows | Max late point | Max late upper | Max revised point | Max revised upper | Max revenue revision |
|---|---:|---:|---:|---:|---:|---:|---:|
| 24h | 0 | 0 | 6.9516% | 7.1543% | 1.9400% | 4.5588% | £23.98 |
| 48h | 5 | 0 | 0.4977% | 0.5601% | 1.2882% | 3.5722% | £11.99 |
| 72h | 8 | 0 | 0.4999% | 0.5612% | 0.7407% | 2.4904% | £11.99 |
| 96h | 9 | 0 | 0.4864% | 0.5485% | 0.3003% | 1.7385% | £0.00 |

The strongest point-estimate candidate is 96h. Nevertheless, its worst simultaneous upper bounds are:

```text
late-event proportion upper = 0.0054850991
budget limit                 = 0.005

revised-cell proportion upper = 0.0173852092
budget limit                  = 0.01
```

Both cross the declared limit.

## Decision contract

The certification selector applies:

```text
shortest candidate
such that:
    simultaneous late-event upper bound passes in every rolling window
    simultaneous revised-cell upper bound passes in every rolling window
    revenue hard gate passes in every rolling window
    paid-subscription hard gate passes in every rolling window
```

Current result:

```text
status = no_candidate_certified_familywise_95
selected_lateness_hours = null
weighted_score_used = false
budget_relaxed_after_uncertainty = false
```

The operating interpretation is deliberately narrower than “96h is unsafe.”

The supported statement is:

> 96h is observed stable in the declared nine-window backtest, but the present sample is not sufficient to certify its proportional risks below the strict budgets at 95% family-wise confidence under the v0.29 binomial model.

## What should happen operationally?

The project retains the v0.28 observed-stability result as descriptive evidence but does not relabel it as statistically certified. The appropriate next actions are to gather more evidence or improve the uncertainty model using a pre-specified method. The project does **not** respond by relaxing the confidence level, shrinking the multiple-comparison family, or increasing the risk budget after seeing the result.

## Generated artifacts

```text
watermark_uncertainty_grid.csv
watermark_uncertainty_summary.csv
watermark_uncertainty_contract.json
watermark_certification_decision.json
```

The full grid retains every candidate × window bound and all individual pass/fail flags. The summary separates `observed_feasible_windows` from `certified_windows` so statistical certification cannot silently overwrite descriptive backtest evidence.

## CI checks

`validate_uncertainty_certification.py` verifies:

- every upper bound is at least the corresponding point estimate;
- bounds remain in [0,1];
- the Bonferroni denominator is exactly the full selection family;
- certification is exactly the conjunction of the two uncertainty gates and two deterministic maximum gates;
- no row can be certified if it is not even point-estimate feasible;
- certified-window counts and rates reconcile;
- the decision selects the shortest all-window certified candidate, or explicitly returns no candidate;
- the budget is not relaxed and no weighted score is used.

`validate_reference_claims.py` separately pins the deterministic v0.29 public result: all four candidates currently have zero certified windows, and 96h's worst upper bounds remain above the two proportional limits.

## Limitations and next step

The largest methodological limitation is dependence. Events and KPI cells can be correlated within calendar days, traffic sources, ingestion batches or other operational clusters. Treating each event/cell indicator as a Bernoulli observation can understate or otherwise mischaracterise uncertainty when those dependencies are material.

A natural next release is therefore **cluster-aware watermark certification**: use calendar-day or defensible processing-batch resampling, compare cluster-aware intervals with the v0.29 exact-binomial bounds, and allow the result either to remain uncertified or to become certifiable without changing the original risk budget.
