-- v0.25 exact-day activity-retention maturity ledger.
-- The analysis boundary is the latest first_open date for each product.
-- App-open events after that boundary may exist in the synthetic source, but
-- they are not allowed to leak into D7/D30 retention before the cohort matures.
WITH analysis_boundary AS (
    SELECT
        product,
        max(CAST(event_ts AS DATE)) FILTER (WHERE event_type = 'first_open') AS analysis_as_of
    FROM silver_events
    GROUP BY 1
),
horizons(horizon_days) AS (
    VALUES (7), (30)
),
acquisitions AS (
    SELECT
        product,
        user_id,
        min(CAST(event_ts AS DATE)) AS cohort_date
    FROM silver_events
    WHERE event_type = 'first_open'
    GROUP BY 1, 2
),
activity AS (
    SELECT DISTINCT
        product,
        user_id,
        CAST(event_ts AS DATE) AS target_date
    FROM silver_events
    WHERE event_type = 'app_open'
),
user_targets AS (
    SELECT
        a.product,
        a.user_id,
        a.cohort_date,
        h.horizon_days,
        a.cohort_date + h.horizon_days AS target_date,
        b.analysis_as_of
    FROM acquisitions a
    CROSS JOIN horizons h
    JOIN analysis_boundary b USING (product)
),
tagged AS (
    SELECT
        u.*,
        u.target_date <= u.analysis_as_of AS mature,
        CASE WHEN act.user_id IS NULL THEN 0 ELSE 1 END AS returned
    FROM user_targets u
    LEFT JOIN activity act
      ON act.product = u.product
     AND act.user_id = u.user_id
     AND act.target_date = u.target_date
),
cohorts AS (
    SELECT
        product,
        cohort_date,
        horizon_days,
        target_date,
        analysis_as_of,
        mature,
        count(*) AS cohort_users,
        sum(returned) AS observed_returns
    FROM tagged
    GROUP BY 1, 2, 3, 4, 5, 6
)
SELECT
    product,
    cohort_date,
    horizon_days,
    target_date,
    analysis_as_of,
    mature,
    CASE WHEN mature THEN 'mature' ELSE 'immature' END AS maturity_status,
    cohort_users,
    CASE WHEN mature THEN cohort_users ELSE 0 END AS eligible_users,
    CASE WHEN mature THEN 0 ELSE cohort_users END AS excluded_users,
    CASE WHEN mature THEN observed_returns ELSE NULL END AS retained_users,
    CASE WHEN mature THEN observed_returns::DOUBLE / cohort_users ELSE NULL END AS retention_rate,
    CASE WHEN mature THEN '' ELSE 'target_date_after_analysis_as_of' END AS exclusion_reason
FROM cohorts
ORDER BY product, horizon_days, cohort_date;
