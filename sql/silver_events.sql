-- Example Silver contract: keep only structurally valid events and one row per event_id.
WITH ranked AS (
    SELECT
        *,
        row_number() OVER (PARTITION BY event_id ORDER BY event_ts, event_id) AS rn
    FROM bronze_events
)
SELECT * EXCLUDE (rn)
FROM ranked
WHERE rn = 1
  AND user_id IS NOT NULL
  AND trim(user_id) <> ''
  AND event_ts IS NOT NULL
  AND revenue_gbp >= 0;
