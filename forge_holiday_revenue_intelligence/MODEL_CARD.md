# Model card

## System purpose

Holiday Revenue Intelligence is a public-data case study for accommodation analytics. It tests how forecasting, behavioural modelling, price references and production monitoring can be connected to explicit commercial decisions.

It is a portfolio/research system. It is **not** a live model for Forge Holiday Group or any other accommodation provider.

## Modules

### Cancellation model

**Target:** `is_canceled`.

**Decision use in the case study:** improve cancellation-aware revenue estimates and identify a limited review population for operational analysis.

**Models:** calibrated Logistic Regression and histogram gradient boosting (HGB).

**Selection:** Logistic Regression is the baseline. HGB can be promoted only from the pre-test validation period if average precision improves by at least 0.01 and Brier score worsens by no more than 0.005. The final test period is not used for champion selection.

**Calibration:** isotonic probability calibration is fitted on a separate calibration period.

**Latest future test:** HGB ROC-AUC 0.839, average precision 0.708, Brier 0.159. The top-risk 10% has an 84.1% cancellation rate versus 31.6% overall.

### Booking-ADR reference

**Target:** average daily rate (ADR) on real bookings with valid positive ADR. Cancelled and non-cancelled bookings are retained.

**Models:** HGB quantile regression for the 0.25, 0.50 and 0.75 quantiles.

**Uncertainty:** split-conformal expansion is estimated on a separate calibration period. Central-50% coverage is then checked on validation and future test periods.

**Latest future test:** median-model MAE 24.71 ADR units; calibrated central-50% interval coverage 46.9% on validation and 39.8% on future test.

**Decision rule:** because future interval coverage degrades, the band remains analyst decision support. It must not be interpreted as an automated dynamic-pricing policy.

### Weekly demand forecast

**Target:** one-week-ahead completed room nights aggregated across the two source hotels.

**Baselines:** previous-year week (`lag_52`) and 4-week rolling mean.

**Candidates:** Ridge and HGB regression, selected using a pre-test validation period.

**Release rule:** a candidate model must improve WAPE by at least 2% relative to the best simple baseline on the future test period.

**Latest result:** the selected Ridge model has WAPE 12.6%; the 4-week rolling baseline has WAPE 8.5%. The complex model is not promoted.

## Point-in-time controls

For cancellation and ADR modelling, booking creation time is inferred as:

`booking_date = arrival_date - lead_time`

The current split is:

- train: booking date before 1 July 2016;
- calibration: 1 July to 30 September 2016;
- validation: 1 October to 31 December 2016;
- test: 1 January 2017 onward.

This reduces a common error where a model is selected using future arrivals that were actually booked much earlier.

The leakage guard blocks outcome/post-outcome fields including:

- `reservation_status`;
- `reservation_status_date`;
- `assigned_room_type`;
- `booking_changes`;
- `days_in_waiting_list`.

The exact timing of every source-system field cannot be proven from the public dataset. A first-party deployment would require a field-level availability contract from the production event model.

## Monitoring

The cancellation module checks:

- population stability index (PSI) for lead time, ADR, stay length, special requests and previous cancellations;
- validation-to-test Brier movement;
- cancellation-adjusted gross-booking-value proxy error.

The current review gate fires when any of the following occurs:

- max PSI > 0.15;
- Brier score worsens by > 0.015;
- absolute gross-value proxy error > 5%.

The latest future period triggers the review gate: max PSI 0.463, Brier +0.025 and gross-value proxy error -12.5%.

A trigger means **review/recalibrate/retrain assessment**, not automatic retraining.

## Policy-sensitive feature test

`deposit_type` is available in the source data and may be available at booking time, but it also reflects commercial policy. Removing it lowers Logistic Regression test average precision from 0.683 to 0.654, a difference of 0.029 in the latest run.

The project keeps this ablation visible because a predictive feature can be operationally unstable if the business changes the policy that created the feature.

## Intended use

Appropriate uses of this repository include:

- demonstrating time-aware model evaluation;
- testing simple versus complex models with fixed release gates;
- showing calibration, drift and revenue-proxy monitoring;
- discussing accommodation data-science architecture;
- preparing a technical interview or portfolio case.

## Out-of-scope uses

Do not use these models to:

- set real customer or property prices;
- infer causal price elasticity;
- deny, restrict or penalise a customer based on cancellation score;
- estimate Forge/Sykes/Forest Holidays performance;
- treat an Inside Airbnb unavailable date as a confirmed booking;
- make claims about a UK holiday-rental population from the non-UK hotel booking records.

## Main limitations

**Domain shift.** The labelled booking data come from two hotels rather than a UK holiday-let marketplace.

**Source-process uncertainty.** Some fields may be updated after initial booking in the original operating system even when their names look booking-time-safe. A real deployment needs source-event timestamps.

**Policy dependence.** Deposit policy affects cancellation signals and must be checked under policy changes.

**Limited forecasting history.** The public dataset covers only a little over two years of arrivals, limiting seasonal forecasting experiments.

**No causal price experiment.** ADR is observational. Demand, inventory and price are jointly determined, so the price module is not an elasticity estimator.

**No direct UK booking labels.** The Greater Manchester short-term-rental source is a market snapshot. Its availability calendar mixes bookings and host blocks.

## Production extension

A real marketplace deployment would require first-party event tables, feature definitions with event timestamps, property-level hierarchy, quote history, search/ranking exposure, booking and cancellation events, owner-block states, promotions, experiment assignments, monitoring ownership and rollback rules.