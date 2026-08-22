-- v0.26 processing-time latency summary under a 48-hour watermark contract.
WITH latency AS (
    SELECT
        product,
        event_type,
        date_diff('second', event_ts, ingested_at) / 3600.0 AS ingestion_delay_hours
    FROM silver_events
)
SELECT
    product,
    event_type,
    count(*) AS events,
    sum(CASE WHEN ingestion_delay_hours > 48.0 THEN 1 ELSE 0 END) AS late_beyond_watermark,
    median(ingestion_delay_hours) AS delay_p50_hours,
    quantile_cont(ingestion_delay_hours, 0.95) AS delay_p95_hours,
    max(ingestion_delay_hours) AS delay_max_hours,
    sum(CASE WHEN ingestion_delay_hours > 48.0 THEN 1 ELSE 0 END)::DOUBLE / count(*) AS late_fraction
FROM latency
GROUP BY 1, 2
ORDER BY 1, 2;
