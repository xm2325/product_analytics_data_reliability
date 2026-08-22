-- SQL implementation of the current compact Silver certification contract.
-- Python additionally supports legacy inputs without ingested_at by treating
-- them as immediate arrivals. Current v0.26 generated sources always include
-- explicit processing time and must satisfy ingested_at >= event_ts.
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
  AND ingested_at IS NOT NULL
  AND ingested_at >= event_ts
  AND revenue_gbp >= 0
  AND product IN ('photo_editor', 'notes_app', 'file_transfer')
  AND event_type IN ('first_open', 'app_open', 'trial_start', 'paid_subscription', 'purchase')
  AND (event_type = 'purchase' OR revenue_gbp = 0);
