# Metric contracts

The workbench treats a metric definition as a versioned contract rather than a label.

| Metric | Numerator | Denominator | Grain | Unit |
|---|---|---|---|---|
| `paid_conversion_from_first_open` | users with `paid_subscription` | users with `first_open` | product | ratio |
| `paid_conversion_from_trial_start` | users with `paid_subscription` | users with `trial_start` | product | ratio |

The same event stream produces materially different values because the denominators answer different questions. Neither should silently replace the other.

The current reference build writes the exact definitions to `metric_contracts.json`; current values are written to `reference_summary.json` rather than hard-coded into this document.

A production metric registry would also record owner, freshness SLA, allowed dimensions, late-arrival policy, and migration version.
