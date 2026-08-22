# Metric contracts

The workbench treats a metric definition as a versioned contract rather than a label.

| Metric | Numerator | Denominator | Grain | Unit | Version |
|---|---|---|---|---|---|
| `daily_active_users` | unique users with `app_open` | not applicable | product-date | users | **2.0** |
| `daily_active_users_legacy_any_event` | unique users with any certified event | not applicable | product-date | users | **1.0-deprecated** |
| `paid_conversion_from_first_open` | users with `paid_subscription` | users with `first_open` | product | ratio | 1.0 |
| `paid_conversion_from_trial_start` | users with `paid_subscription` | users with `trial_start` | product | ratio | 1.0 |

## Why DAU changed

The original compact public release counted a user as active when they generated any certified event. That makes data processing easy, but the semantics are weak: a delayed purchase or subscription event is a commercial state transition, not necessarily evidence that the user opened or used the product that day.

v0.24 therefore introduces an explicit `app_open` event and makes it the current DAU activity signal.

The old metric is not silently overwritten. Gold keeps both definitions during migration:

```text
dau                       # v2: app_open users
dau_legacy_any_event      # v1: any-event users
dau_definition_delta      # v1 - v2
```

The reference build writes the daily dual-run to `dau_definition_migration.csv` and a product summary to `dau_definition_migration_summary.csv`.

## Migration rule

A metric-definition change is treated as a data-product migration:

1. define and version the new contract;
2. run old and new definitions on the same certified events;
3. quantify the difference before switching downstream use;
4. keep the old definition explicitly deprecated during the comparison period;
5. update forecasting and retention consumers to the new contract only after validation.

The same principle applies to conversion metrics: denominator choice is part of the contract, not a dashboard formatting detail.

The generated `metric_contracts.json` is the machine-readable source for exact definitions. A production registry would additionally record owner, freshness SLA, allowed dimensions, late-arrival policy and deprecation date.
