# Reference results and interpretation

This document records the compact public reference outputs from the broader workbench. All results use synthetic data or explicit planning stress tests.

## Data reliability

Controlled duplicate/revenue faults cause raw revenue to exceed certified revenue by **9.2–12.2%** across the three reference products. The value is useful because the fault is known: the exercise checks whether validation and reconciliation recover a trustworthy metric rather than whether an anomaly detector happens to notice a shift.

An idempotent correction/replay contract produces **£0.00 second-run delta**. A correction that changes the KPI again on retry is treated as operationally unsafe even if its first run was numerically correct.

## Metric semantics

Two conversion contracts intentionally answer different questions:

- paid users / first-open users: **18.0%**;
- paid users / trial-start users: **56.6%**.

The difference is semantic, not a contradiction. Denominator choice is therefore stored as part of the metric contract.

## Forecast governance

The reference rolling-origin evaluation approves **3 DAU forecasts** for planning and withholds **6 revenue/subscription forecasts**. The gate separates successful model execution from approval for a business decision.

Non-significance or a successful model fit is not treated as evidence of operational readiness.

## Risk-aware price-test allocation

The planning problem is to retain useful evidence while reducing exposure to a potentially harmful higher-price variant.

For **700 balanced-equivalent information units** under an equal-variance planning assumption:

| Design | Total users | Higher-price users | Approx. readout |
|---|---:|---:|---:|
| 50/50 | 700 | 350 | 184 d |
| 20/80 candidate | 1,094 | 219 | 270 d |

The 20/80 candidate reduces higher-price exposure by **37.4%**, but uses more total traffic and takes longer. In the reference portfolio stress test it also satisfies the separately declared limits for commercial ES95, expected unsafe exposure and tail concentration.

The result is **not** a claim that 20/80 is universally optimal. The design depends on arm-specific variance. The broader stress test found the reference pass could disappear when treatment-arm standard deviation rose to roughly 1.10× control, so arm variance must be measured before adopting the allocation.

## Why the risk constraints stay separate

The workbench does not form a weighted score such as `revenue - λ × customer harm`. Commercial regret, customer exposure and portfolio concentration remain separate constraints. Passing one budget cannot pay for violating another.
