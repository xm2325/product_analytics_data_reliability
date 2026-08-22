# Metric contracts

The workbench treats a metric definition as a versioned contract rather than a label.

| Metric | Numerator | Denominator | Primary use |
|---|---|---|---|
| `paid_conversion_from_first_open` | users with `paid_subscription` | users with `first_open` | broad acquisition-to-paid funnel |
| `paid_conversion_from_trial_start` | users with `paid_subscription` | users with `trial_start` | conditional trial-to-paid conversion |

The reference synthetic run produces materially different values (18.0% versus 56.6%) because the denominators answer different questions. Neither should silently replace the other.

A production metric registry would also record owner, freshness SLA, allowed dimensions, late-arrival policy, and migration version.
