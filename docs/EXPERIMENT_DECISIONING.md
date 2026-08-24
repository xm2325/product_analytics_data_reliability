# Decision-grade product experimentation

v0.32 adds a reproducible product-experiment decision path to the workbench. The objective is not to maximize the chance of a rollout decision. It is to make the experiment validity check, effect estimates, guardrails and final action independently reproducible from the generated user-level evidence.

## Reference question

The controlled reference asks whether a pricing treatment should roll out when it appears to increase 30-day revenue but may reduce 30-day paid conversion.

The deterministic reference uses 8,000 synthetic experiment users with exactly 4,000 control and 4,000 treatment assignments.

## Pre-specified contract

Assignment integrity is checked before treatment effects are allowed to drive a rollout decision. The reference uses an exact two-sided binomial sample-ratio-mismatch test with expected treatment share 0.5 and `alpha = 0.001`.

The primary metric is `revenue_gbp_30d`. Its treatment effect is estimated by ANCOVA with `pre_revenue_gbp_30d` as a pre-period covariate and HC3 heteroskedasticity-robust standard errors. The primary gate requires the lower bound of a 95% two-sided confidence interval to be above zero.

The guardrail metric is `paid_subscription_30d`. Its treatment-control difference is estimated as a difference in proportions with a 95% two-sided normal confidence interval. The non-inferiority margin is -3 percentage points. The guardrail passes only when the lower confidence bound is strictly greater than -0.03.

The gates are non-compensatory. A large revenue effect cannot offset a failed paid-conversion guardrail. If assignment integrity fails, the experiment action is `invalid`, not `hold` or `rollout`.

## Reference result

The deterministic `seed=2206` reference produces:

```text
assignment                    4,000 control / 4,000 treatment
SRM p-value                   1.000
revenue effect                +£0.6851 per user over 30 days
revenue 95% CI                [£0.5514, £0.8187]
paid-conversion effect        -1.625 percentage points
paid-conversion 95% CI        [-3.363, +0.113] percentage points
paid harm margin              -3.000 percentage points
final action                  HOLD
```

This result is deliberately not a rollout. The paid-conversion point estimate, -1.625 percentage points, is inside the allowed -3 percentage-point harm margin. However, the lower confidence bound is about -3.363 percentage points, which crosses the margin. The experiment therefore lacks enough evidence to clear the guardrail even though the revenue effect is decisively positive.

The decision contract is:

```text
assignment_integrity_gate = PASS
revenue_gate              = PASS
paid_guardrail_gate        = FAIL
weighted_score_used        = false
final_action               = hold
```

## Generated evidence

The reference build writes four experiment artifacts:

```text
pricing_experiment_users.csv
pricing_experiment_estimates.csv
pricing_experiment_contract.json
pricing_experiment_decision.json
```

`pricing_experiment_users.csv` is the source evidence. `pricing_experiment_estimates.csv` stores the primary and guardrail estimates. The contract records metric definitions, confidence level, SRM threshold and non-compensatory decision semantics. The decision artifact stores assignment-integrity evidence and the final gate state.

## Independent validation

`scripts/validate_pricing_experiment.py` does not trust the generated estimate table. It reloads the user-level artifact and independently recomputes:

- exact assignment balance and the binomial SRM p-value;
- ANCOVA with HC3 robust uncertainty for revenue;
- the paid-conversion difference and its confidence interval;
- the final non-compensatory gate state;
- the pinned deterministic reference effects.

The validator also checks that the reference demonstrates the intended statistical boundary:

```text
paid point estimate > -0.03
paid lower 95% CI   < -0.03
```

A method, seed, data-generation or serialization change that moves a published reference number must therefore fail validation until the evidence and public claim are reviewed together.

## Scope boundary

The reference is synthetic. It demonstrates experiment-analysis and decision-system behaviour; it is not evidence about any real product, customer population or pricing policy.

The current guardrail uses a large-sample normal interval for a difference in proportions. The reference sample is large and the event rates are not near zero or one, so that approximation is appropriate for this controlled case. The workbench does not claim that this interval should be used for sparse or highly imbalanced production experiments without checking its assumptions.

The experiment is a fixed-horizon analysis. Sequential monitoring, repeated peeking, network interference and cross-experiment interaction are not part of the v0.32 claim.
