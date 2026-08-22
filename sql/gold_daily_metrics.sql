-- Gold daily metrics with the v0.24 DAU dual-run.
-- `dau` is the current v2 definition: unique users with app_open.
-- `dau_legacy_any_event` is retained temporarily for migration analysis.
WITH daily AS (
    SELECT
        product,
        CAST(event_ts AS DATE) AS date,
        count(DISTINCT CASE WHEN event_type = 'app_open' THEN user_id END) AS dau,
        count(DISTINCT user_id) AS dau_legacy_any_event,
        count(DISTINCT CASE WHEN event_type = 'first_open' THEN user_id END) AS first_open,
        count(DISTINCT CASE WHEN event_type = 'trial_start' THEN user_id END) AS trial_start,
        count(DISTINCT CASE WHEN event_type = 'paid_subscription' THEN user_id END) AS paid_subscription,
        sum(CASE WHEN event_type = 'purchase' THEN revenue_gbp ELSE 0 END) AS revenue_gbp
    FROM silver_events
    GROUP BY 1, 2
)
SELECT
    product,
    date,
    dau,
    dau_legacy_any_event,
    dau_legacy_any_event - dau AS dau_definition_delta,
    CAST(dau_legacy_any_event - dau AS DOUBLE) / NULLIF(dau, 0) AS dau_definition_delta_pct,
    first_open,
    trial_start,
    paid_subscription,
    revenue_gbp,
    CAST(paid_subscription AS DOUBLE) / NULLIF(first_open, 0) AS conversion_first_open,
    CAST(paid_subscription AS DOUBLE) / NULLIF(trial_start, 0) AS conversion_trial_start
FROM daily
ORDER BY product, date;
