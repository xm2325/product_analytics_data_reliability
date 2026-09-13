# Business case

## Commercial framing

A holiday-rental data-science team does not need a model because a benchmark score is interesting. It needs a decision that can improve revenue, conversion, service reliability, owner outcomes or operating efficiency without creating avoidable risk.

This project therefore starts with four operational questions.

| Question | Analytical output | Commercial use | Guardrail |
|---|---|---|---|
| Which bookings carry more cancellation risk? | calibrated cancellation probability and top-capacity ranking | cancellation-aware revenue planning, operations review | do not use as an adverse customer-action rule |
| What booking ADR is typical for similar observed bookings? | conditional median and uncertainty band | analyst price/reference checks | no causal elasticity or automatic optimal-price claim |
| What room-night volume should we expect next week? | baseline and candidate forecasts | capacity and demand planning | complex model must beat the simple baseline |
| Can the model still be trusted later? | PSI, calibration movement, revenue-proxy error | review/recalibration/retraining decision | monitoring trigger is not automatic retraining |

## 1. Cancellation-aware revenue reliability

A booking value is not the same as realised revenue if cancellations are material. The workflow therefore combines booking value with calibrated cancellation probability to produce a simple expected gross-value proxy.

The latest future test shows that the selected HGB model has useful ranking power, but the predicted non-cancelled gross-value proxy is 12.5% below the observed value. At the same time, lead-time/ADR distributions and probability calibration move enough to trigger the model-review gate.

Commercial decision: **do not rely on the frozen model without review simply because ROC-AUC remains high**.

In a first-party system, this module would feed revenue forecasts, inventory/rebooking analysis and operational review rather than customer restrictions.

## 2. Demand forecasting with a baseline-first rule

The forecasting module asks a simple question: does a statistical/ML candidate provide enough value over a cheap and transparent baseline to justify deployment and maintenance?

On the future test period:

- 4-week rolling mean WAPE: 8.5%;
- seasonal previous-year WAPE: 12.1%;
- selected Ridge candidate WAPE: 12.6%.

The candidate fails the pre-set release gate, so the 4-week rolling baseline remains the operational choice.

Commercial decision: **keep the simpler forecast**. A more complex model has no commercial value if it is less accurate and more expensive to operate.

With first-party holiday-let data, the next version would forecast destination/property demand using booking pace, search demand, lead time, inventory, school/bank holidays, weather and promotions, with hierarchical reconciliation across property, destination and group levels.

## 3. Pricing as a reference problem, not a false causal claim

Observed prices are affected by demand, inventory, property quality, time of year, channel, policy and prior commercial decisions. A supervised model of observed ADR cannot by itself answer: "What would have happened if the price had been £10 higher?"

The current module therefore estimates a comparable-booking ADR distribution and calibrates its interval on a later period.

The future test shows:

- median-model MAE: 24.71 ADR units;
- calibrated central-50% coverage: 46.9% on validation and 39.8% on future test.

The fall in future coverage is a warning against automating price changes from this public benchmark.

Commercial decision: **use as analyst context only**.

A production pricing system would need quote history, availability and booking outcomes at each offered price, promotions, property controls and preferably randomised or quasi-experimental variation before estimating price elasticity or incremental revenue.

## 4. Production model health

The project separates three questions:

1. Is the input population changing?
2. Is probability/forecast performance changing?
3. Is the business quantity that matters changing enough to require action?

The cancellation monitor checks PSI, Brier movement and cancellation-adjusted gross-value error. The current future period triggers review on all three dimensions strongly enough that a technical owner should investigate calibration, feature distributions and the business process before continuing with the frozen version.

Commercial decision: **review before trusting the next period**.

## What first-party marketplace data would unlock

The public case cannot directly test personalisation, search ranking or causal pricing. With first-party data, the same project structure would extend to:

**Demand and supply:** property availability, owner blocks, confirmed bookings, search demand, booking pace, cancellation/rebooking, destination capacity.

**Pricing:** quote history, displayed price, discounts, fees, competitor/market context, promotions, conversion, realised revenue, owner constraints.

**Personalisation and ranking:** search query, filters, impressions, position, clicks, saves, booking, repeat-customer history and session context.

**Experimentation:** randomised price/ranking/personalisation interventions or carefully designed quasi-experiments with pre-defined guardrails.

**Production:** feature-store contracts, model registry, calibration checks, incident ownership, rollback, retraining criteria and commercial KPI monitoring.

## Why this is a useful senior-level case

The main evidence is not that every model wins. The evidence is that the workflow can make and defend a release decision:

- one challenger is selected using validation only;
- the selected model is later flagged for review when the data change;
- another complex model is rejected because a simple baseline wins;
- a pricing model is restricted to analyst support because uncertainty coverage weakens;
- source limitations are kept visible rather than hidden behind a polished metric.

That is the behaviour expected from a production data-science function whose models affect commercial decisions.
