# Holiday Revenue Intelligence

Real-data machine-learning case study for accommodation and holiday-rental commercial decisions.

> This is an independent portfolio project using public data. It is not affiliated with Forge Holiday Group, Sykes Holiday Cottages, Forest Holidays, Airbnb, or the hotels represented in the public booking dataset. No company-private data is used.

## Business question

How should an accommodation marketplace use data science to support demand planning, cancellation-aware revenue estimates, pricing references, and reliable model operation without shipping a model simply because its offline score looks strong?

The project treats the model as one part of a decision system. Each module has a simple baseline, a time-ordered evaluation, an explicit release or review rule, and a clear limit on what the data can support.

## What is implemented

The current workflow contains four connected modules:

1. **Cancellation and behavioural modelling** — calibrated Logistic Regression and histogram gradient boosting, with a policy-sensitive feature ablation and a fixed-capacity risk view.
2. **Demand forecasting** — weekly completed room-night forecasting with rolling and seasonal baselines; the more complex model must beat the best simple baseline before promotion.
3. **Pricing reference** — quantile models and split-conformal interval calibration for booking ADR. This is a comparable-booking reference, not a price-elasticity or optimal-price model.
4. **Production monitoring** — population stability index (PSI), Brier-score movement, revenue-proxy error, explicit review gates, tests, and GitHub Actions CI.

A one-time **Greater Manchester short-term-rental market audit** is also supported with Inside Airbnb public data. It is disabled in CI so the source files are not downloaded repeatedly.

## Current validated result

The latest CI run uses a point-in-time split based on an inferred booking creation date:

`booking_date = arrival_date - lead_time`

Model training, probability calibration, model selection, and final testing use separate chronological periods. The final test period is not used to select the cancellation champion.

| Decision area | Future-period result | Decision |
|---|---:|---|
| Cancellation ranking | HGB ROC-AUC **0.839**, AP **0.708**, Brier **0.159** | HGB selected on the earlier validation period |
| Top-risk capacity | Top 10% cancellation rate **84.1%** vs **31.6%** overall | Useful prioritisation signal, not a customer-action rule |
| Policy-feature check | Removing `deposit_type` lowers Logistic Regression test AP by **0.029** | Treat policy-sensitive features with care |
| Model monitoring | max PSI **0.463**, Brier change **+0.025**, gross-value proxy error **-12.5%** | **Review/recalibration flag triggered** |
| Demand forecast | 4-week rolling WAPE **8.5%** vs selected Ridge **12.6%** | **Do not promote** the complex model |
| ADR reference | median-model test MAE **24.71** ADR units | Keep as decision support only |
| ADR interval reliability | central-50% coverage **46.9%** on validation, **39.8%** on future test | Future under-coverage; do not automate pricing from this band |

This result is intentionally not rewritten into a success story. Two commercially important conclusions are negative: the complex demand model is rejected in favour of a simple baseline, and the later data trigger a monitoring review for the cancellation model.

## Why the negative results matter

A production data-science team should be able to say **do not ship**. In this run:

- HGB earns promotion for cancellation modelling on the pre-test validation period, but later distribution and calibration movement trigger a review.
- Ridge is the better complex forecasting candidate on validation, but it still loses to a simple 4-week rolling baseline on the future test period, so it is not promoted.
- The ADR reference interval improves after conformal calibration, but future coverage remains below its nominal target. It stays an analyst reference rather than an automated pricing rule.

The project therefore demonstrates model selection, failure detection, and decision gates rather than metric chasing.

## Data

### Real hotel booking behaviour

The core modelling data are the public **Hotel Booking Demand** records described by Antonio, Almeida and Nunes (Data in Brief, 2019; DOI: `10.1016/j.dib.2018.11.126`). The full data contain **119,390 real bookings** from a resort hotel and a city hotel, including arrivals and cancellations from July 2015 to August 2017.

These hotels are **not UK holiday rentals**. The data are used because they provide real booking, cancellation, lead-time and ADR behaviour. Domain transfer to a UK holiday-let marketplace is treated as a limitation, not assumed.

### UK market layer

A separate one-time audit uses the **25 December 2024 Greater Manchester Inside Airbnb snapshot**. The first controlled run found 4,443 `Entire home/apt` listings in the 180-day analysis window. The calendar does not identify whether an unavailable night is booked or host-blocked, so unavailable dates are never labelled as bookings. The snapshot also showed effectively static asking prices within listing across the forward calendar, so it is not used to estimate dynamic price response.

Raw Inside Airbnb data are not committed to this repository and the optional UK step is off in CI.

See [DATA_SOURCES.md](DATA_SOURCES.md) for source and data-use details.

## Point-in-time design

The cancellation and ADR modules split by **booking creation time**, not arrival time. This matters because a long-lead booking arriving in the test period may have been created much earlier.

The current booking-time partitions are:

- training: before 1 July 2016;
- probability/interval calibration: 1 July to 30 September 2016;
- validation and model selection: 1 October to 31 December 2016;
- untouched future test: 1 January 2017 onward.

Outcome fields such as `reservation_status` and `reservation_status_date` are blocked by a leakage guard and are not model features.

## Repository structure

```text
forge_holiday_revenue_intelligence/
├── README.md
├── BUSINESS_CASE.md
├── DATA_SOURCES.md
├── MODEL_CARD.md
├── DECISION_LOG.md
├── requirements.txt
├── sql/
│   └── booking_point_in_time_features.sql
├── src/
│   ├── core.py
│   └── run_pipeline.py
├── tests/
│   ├── test_core.py
│   └── test_time_split.py
└── reports/
    └── generated/        # produced by CI/local runs; not source data
```

## Run locally

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pytest -q
python src/run_pipeline.py --output-dir reports/generated
```

The normal run fetches the public Hotel Booking Demand mirror and does **not** fetch Inside Airbnb.

For a one-time Greater Manchester market audit:

```bash
python src/run_pipeline.py \
  --output-dir reports/generated \
  --include-uk-market
```

Please follow the source provider's data-use guidance and avoid repeated downloads.

## What would change with first-party holiday-rental data

With marketplace event and inventory data, the next production version would replace proxies with direct labels and add:

- search impressions, property views, ranking position and booking conversion;
- quote history and actual price changes;
- property availability, owner blocks and confirmed bookings as separate states;
- promotions, channel, cancellation policy and owner interventions;
- destination, property and lead-time hierarchies;
- experiment or quasi-experiment evidence before claiming price elasticity;
- property-level and destination-level forecast reconciliation;
- post-deployment revenue, conversion, guest and owner guardrails.

That is the point where pricing optimisation, personalisation and ranking can be evaluated directly rather than inferred from public proxies.