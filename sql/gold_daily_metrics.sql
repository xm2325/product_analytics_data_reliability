-- Example Gold model. The Python implementation additionally calculates
-- versioned conversion metrics from explicit denominators.
SELECT
    product,
    CAST(event_ts AS DATE) AS date,
    count(DISTINCT user_id) AS dau,
    count(DISTINCT CASE WHEN event_type = 'first_open' THEN user_id END) AS first_open,
    count(DISTINCT CASE WHEN event_type = 'trial_start' THEN user_id END) AS trial_start,
    count(DISTINCT CASE WHEN event_type = 'paid_subscription' THEN user_id END) AS paid_subscription,
    sum(CASE WHEN event_type = 'purchase' THEN revenue_gbp ELSE 0 END) AS revenue_gbp
FROM silver_events
GROUP BY 1, 2
ORDER BY 1, 2;
