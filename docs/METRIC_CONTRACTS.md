# Metric contracts

The workbench treats a metric definition as a versioned contract rather than a dashboard label.

| Metric | Numerator | Denominator | Grain | Unit | Version |
|---|---|---|---|---|---|
| `daily_active_users` | unique users with `app_open` | not applicable | product-date | users | **2.0** |
| `daily_active_users_legacy_any_event` | unique users with any certified event | not applicable | product-date | users | **1.0-deprecated** |
| `paid_conversion_from_first_open` | users with `paid_subscription` | users with `first_open` | product | ratio | 1.0 |
| `paid_conversion_from_trial_start` | users with `paid_subscription` | users with `trial_start` | product | ratio | 1.0 |

## DAU migration

The original compact release counted any certified event as activity. v0.24 introduced explicit `app_open` behaviour and migrated the current DAU contract to `unique users with app_open` while retaining the old definition for a dual-run comparison.

```text
dau                       # v2: app_open users
dau_legacy_any_event      # v1: any-event users, deprecated
dau_definition_delta      # v1 - v2
```

The current reference build writes the daily comparison to `dau_definition_migration.csv` and the product summary to `dau_definition_migration_summary.csv`.

## Retention contracts and denominator maturity

v0.25 makes retention maturity part of the metric contract rather than an implicit filter.

| Contract | Cohort | Return | Horizon | Return window | Eligible denominator |
|---|---|---|---:|---|---|
| `d7_activity_retention` | first `first_open` | `app_open` | 7 d | exact calendar day | cohort users whose D7 target date is on or before `analysis_as_of` |
| `d30_activity_retention` | first `first_open` | `app_open` | 30 d | exact calendar day | cohort users whose D30 target date is on or before `analysis_as_of` |

The generated `retention_contracts.json` is the machine-readable source. The reference analysis uses the final acquisition date as `analysis_as_of`. A follow-up `app_open` may already exist later in the synthetic source, but it cannot be used for a cohort whose target date lies after that reporting boundary.

`retention_maturity_ledger.csv` records every product × cohort-date × horizon combination with:

```text
target_date
analysis_as_of
mature / immature
cohort_users
eligible_users
excluded_users
retained_users
retention_rate
exclusion_reason
```

Immature cohorts stay visible, but `retained_users` and `retention_rate` are intentionally null. This prevents future information from being interpreted as current evidence.

The maturity fraction is not itself a behavioural KPI. A lower D30 eligible fraction means more cohorts have not yet had 30 days to mature; it does **not** mean retention is worse.

## Migration rule

A metric-definition change is treated as a data-product migration:

1. define and version the new contract;
2. run old and new definitions on the same certified events;
3. quantify the difference before switching downstream use;
4. keep the old definition explicitly deprecated during comparison;
5. make denominator maturity and observation boundaries machine-readable;
6. validate Python and SQL implementations against the same contract.

A production registry would additionally record owner, freshness SLA, allowed dimensions, late-arrival policy and deprecation date.
