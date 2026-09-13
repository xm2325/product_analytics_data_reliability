-- Point-in-time booking feature contract for an accommodation cancellation model.
--
-- Assumption: `hotel_bookings_clean` contains a parsed DATE `arrival_date`
-- plus the original booking fields. `lead_time` is the number of days between
-- booking creation and arrival. The target is retained only for model training;
-- post-outcome status fields are intentionally excluded from the feature set.
--
-- This SQL is written in DuckDB/PostgreSQL-style syntax and is intended to show
-- the warehouse feature boundary that should precede the Python model pipeline.

WITH booking_time AS (
    SELECT
        arrival_date,
        arrival_date - CAST(lead_time AS INTEGER) * INTERVAL '1 day' AS booking_date,
        CAST(lead_time AS INTEGER) AS lead_time,
        arrival_date_week_number,
        arrival_date_day_of_month,
        arrival_date_month,
        hotel,
        meal,
        country,
        market_segment,
        distribution_channel,
        reserved_room_type,
        deposit_type,
        customer_type,
        stays_in_weekend_nights,
        stays_in_week_nights,
        adults,
        children,
        babies,
        is_repeated_guest,
        previous_cancellations,
        previous_bookings_not_canceled,
        adr AS average_daily_rate,
        required_car_parking_spaces,
        total_of_special_requests,
        is_canceled
    FROM hotel_bookings_clean
    WHERE arrival_date IS NOT NULL
      AND lead_time IS NOT NULL
),
feature_snapshot AS (
    SELECT
        booking_date,
        arrival_date,
        lead_time,
        arrival_date_week_number,
        arrival_date_day_of_month,
        arrival_date_month,
        hotel,
        meal,
        country,
        market_segment,
        distribution_channel,
        reserved_room_type,
        deposit_type,
        customer_type,
        stays_in_weekend_nights,
        stays_in_week_nights,
        adults,
        children,
        babies,
        is_repeated_guest,
        previous_cancellations,
        previous_bookings_not_canceled,
        average_daily_rate,
        required_car_parking_spaces,
        total_of_special_requests,
        is_canceled AS target_is_canceled
    FROM booking_time
)
SELECT *
FROM feature_snapshot
ORDER BY booking_date, arrival_date;

-- Deliberately absent from the feature snapshot:
--   reservation_status
--   reservation_status_date
--   assigned_room_type
--   booking_changes
--   days_in_waiting_list
--
-- A production implementation should replace this static exclusion list with a
-- field-level event-time contract proving exactly when every feature becomes known.
