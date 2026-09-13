# Data sources and boundaries

This project uses public data only. No Forge Holiday Group, Sykes Holiday Cottages, Forest Holidays, Bachcare, Airbnb-private, or other employer-private data are used.

## 1. Hotel Booking Demand

**Use in this project:** cancellation modelling, booking-ADR reference modelling, completed room-night forecasting, calibration and monitoring.

**Original data article:** Nuno Antonio, Ana de Almeida and Luis Nunes, *Hotel booking demand datasets*, Data in Brief 22 (2019), 41–49. DOI: `10.1016/j.dib.2018.11.126`.

**Public mirror used by the reproducible pipeline:**

`https://raw.githubusercontent.com/rfordatascience/tidytuesday/main/data/2020/2020-02-11/hotels.csv`

The original article reports two real hotel datasets: 40,060 resort-hotel bookings and 79,330 city-hotel bookings, for 119,390 observations in total. Each record represents a booking, including bookings that arrived and bookings that were cancelled. Direct hotel and customer identifiers were removed.

### Important boundary

These are real accommodation bookings, but they are not UK holiday-rental marketplace records. The project uses them to test statistical and production logic around lead time, ADR, cancellation, temporal validation and revenue reliability. Results are not presented as estimates of Forge/Sykes customer behaviour.

## 2. Inside Airbnb — Greater Manchester

**Use in this project:** one-time UK short-term-rental market audit and source-quality check.

**Source:** `https://insideairbnb.com/get-the-data/`

**Snapshot used:** Greater Manchester, England, 25 December 2024.

The controlled analysis used the detailed listings and calendar files and restricted the main audit to `Entire home/apt` listings.

Inside Airbnb states that its public calendar does **not** distinguish a booked night from a host-blocked unavailable night. Therefore this project never treats `available = false` as a confirmed booking label. It is only an availability-pressure proxy.

The same snapshot showed effectively static forward-calendar asking prices within each listing in the fields used by the audit. That finding is retained as a data-quality result: the project does not use this snapshot to estimate dynamic price response.

### Data-use rule in this repository

Raw Inside Airbnb files are not committed or republished. The UK market step is disabled by default and disabled in CI. It can be run manually with `--include-uk-market` when a fresh one-time source audit is required. This avoids repeatedly downloading the source files during routine CI.

Inside Airbnb publishes its downloadable data under CC BY 4.0 and also asks analysts not to republish the raw data and not to repeatedly scrape/download it.

## 3. VisitBritain / VisitEngland domestic tourism statistics

**Use in this project:** commercial and market context only. These statistics are not model-training rows in the current pipeline.

Sources:

- `https://www.visitbritain.org/research-insights/domestic-tourism-latest-results`
- `https://www.visitbritain.org/research-insights/england-domestic-tourism-regional-and-subregional-data`

The 2025 releases provide monthly, quarterly and annual volume/value estimates for domestic overnight trips and day visits. VisitBritain also reports regional, county and town-level statistics. For example, its 2025 top-town results report approximately 5.3 million overnight trips for Manchester.

These data are useful for checking the scale and seasonality of the UK domestic-tourism market, but the current release does not force a low-frequency survey series into a high-frequency ML target.

## Reproducibility and provenance

The pipeline logs the source URL used for the real booking dataset. Generated metrics include the sample counts and time ranges used by each model. Source data are not silently replaced with synthetic data.

The project intentionally keeps source roles separate:

- Hotel Booking Demand: direct real booking/cancellation labels, non-UK;
- Inside Airbnb Greater Manchester: UK short-term-rental market snapshot, but no confirmed-booking label;
- VisitBritain: official UK tourism context, not a booking-level training set.

This separation is important because combining the sources does not make the hotel records UK holiday-let records, and the project does not claim otherwise.
