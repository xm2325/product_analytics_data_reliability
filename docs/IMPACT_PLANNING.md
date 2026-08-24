# Decision-aware impact planning

v0.33 adds one layer after experiment decisioning: translate a validated 30-day treatment effect into an explicit product-planning scenario **without turning a HOLD experiment into a rollout forecast**.

The reference remains synthetic. Eligible-user counts, adoption shares and resulting revenue values are planning assumptions, not company scale estimates or production forecasts.

## Decision chain

```text
assignment integrity
    ↓
30-day revenue effect + uncertainty
    ↓
paid-conversion non-inferiority guardrail
    ↓
experiment action = HOLD
    ↓
conditional evidence plan + counterfactual launch scenario
    ↓
no authorised rollout impact until the guardrail clears
```

The impact layer is downstream of the experiment decision. It never overrides that decision.

## Reference experiment input

The v0.32 controlled experiment is unchanged:

```text
4,000 control / 4,000 treatment
SRM p-value = 1.000

30d revenue effect = +£0.685080829 per treated user
95% CI             = [£0.551429745, £0.818731912]

paid conversion effect = -1.625 percentage points
95% CI                  = [-3.363352, +0.113352] percentage points
harm margin             = -3.000 percentage points

revenue gate       = PASS
paid guardrail     = FAIL
experiment action  = HOLD
```

The revenue result is positive. The paid-conversion point estimate is also inside the pre-specified -3pp margin. The lower confidence bound nevertheless crosses the margin, so the experiment does not authorise rollout.

## Conditional guardrail evidence target

The experiment guardrail uses a two-sided 95% normal confidence interval for the treatment-control difference in proportions. The existing implementation obtains its standard error through sample variances with `ddof=1`.

v0.33 preserves that exact convention for prospective planning rather than switching silently to a slightly different Bernoulli variance formula.

For observed control and treatment paid-conversion rates `p_c` and `p_t`, equal future arm size `n`, and `z = 1.96`, the projected lower bound is

```text
(p_t - p_c)
  - z * sqrt(
      [p_c(1-p_c) + p_t(1-p_t)] / (n - 1)
    )
```

The denominator `n - 1` is the projected form of the experiment's `ddof=1` sample-variance convention.

Reference observed rates are:

```text
control paid conversion   = 20.375%
treatment paid conversion = 18.750%
difference                = -1.625pp
```

The current 4,000-per-arm lower bound is the same value reported by the experiment validator:

```text
-3.363352pp
```

The conditional evidence search asks for the **smallest equal arm size** whose projected lower bound is strictly greater than -3pp while holding the observed arm rates fixed.

```text
minimum target per arm = 6,393
current per arm        = 4,000
additional per arm     = 2,393
```

The integer boundary is audited directly: 6,393 passes the projected rule and 6,392 does not.

This is not a power guarantee and not a promise that another 2,393 users per arm will clear the guardrail. Future conversion rates can move. The claim is conditional:

> If the observed arm rates remained representative, 6,393 users per arm would be the first equal-allocation sample size whose projected confidence lower bound clears the current -3pp rule.

If the observed treatment-control point estimate itself were at or below -3pp, the planner would return `structural_point_estimate_failure` rather than pretend more sample can repair the result.

## Fixed-volume launch cohorts

The counterfactual business scenario uses three synthetic launch cohorts entering over 90 calendar days:

| Cohort | Eligible users | Hypothetical adoption | Hypothetical treated users |
|---|---:|---:|---:|
| 1 | 100,000 | 25% | 25,000 |
| 2 | 100,000 | 50% | 50,000 |
| 3 | 100,000 | 75% | 75,000 |
| **Total** | **300,000** | — | **150,000** |

Each cohort contributes only its own first 30-day revenue outcome. The project does **not** multiply the 30-day effect by three and does not claim a 90-day lifetime-value effect.

With fixed hypothetical treated-user counts, uncertainty propagation is deliberately transparent:

```text
counterfactual impact
  = treated users × experiment revenue effect

counterfactual impact CI
  = treated users × experiment revenue-effect CI
```

Reference totals are:

```text
counterfactual treated users        = 150,000
counterfactual incremental revenue  = £102,762.12
95% interval                        = [£82,714.46, £122,809.79]
```

These values answer a planning question only:

> What would the validated 30-day revenue effect imply under this synthetic fixed-volume launch ramp?

They do not answer whether the product should launch.

## HOLD-aware authorisation

The experiment decision is applied after the counterfactual scenario is calculated:

```text
experiment action                  = HOLD
planning status                    = counterfactual_only
decision-authorised rollout        = false
authorised treated users           = 0
authorised incremental revenue     = null
```

The distinction is intentional. A positive expected impact remains visible for planning, but the repository refuses to relabel it as realised, forecast or authorised impact while a non-compensatory guardrail fails.

For an `INVALID` experiment, the planner also authorises no rollout. Only a `ROLLOUT` experiment can convert the same fixed-volume scenario into decision-authorised planning evidence.

## Generated artifacts

```text
pricing_impact_scenario.csv
pricing_impact_contract.json
pricing_guardrail_evidence_plan.json
pricing_impact_decision.json
```

The impact contract explicitly records:

```text
no_ltv_extrapolation = true
no_effect_persistence_beyond_30d_assumed = true
synthetic_scale_only = true
```

## Independent validation

`scripts/validate_impact_plan.py` does not trust the stored planning outputs. It reloads the user-level experiment data and independently verifies:

- the paid-conversion arm rates and current confidence lower bound;
- equality with the v0.32 guardrail CI definition;
- the 6,393-per-arm minimum integer boundary and 2,393-per-arm increment;
- the 25k / 50k / 75k treated-user launch ramp;
- the revenue effect and confidence interval source from experiment evidence;
- the 150,000-user counterfactual impact totals;
- `HOLD → counterfactual_only`;
- zero authorised treated users and a null authorised revenue claim.

The public `results/reference_summary.csv` is then checked against the generated summary by `scripts/validate_static_claim_ledger.py`.

## Interpretation boundary

This layer intentionally does not model:

- persistence of the 30-day effect beyond 30 days;
- treatment saturation or diminishing returns at larger rollout fractions;
- acquisition-channel mix shifts;
- interference between treated and control users;
- sequential experiment monitoring or repeated peeking;
- future paid-conversion rates changing as more evidence arrives;
- costs, taxes, refunds, platform fees or contribution margin.

Those would require additional assumptions or data. v0.33 is narrower: make the decision boundary and its business implication explicit without claiming more than the experiment supports.
