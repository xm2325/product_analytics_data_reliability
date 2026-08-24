# Forecast decisioning and performance tracking

v0.34 upgrades the forecasting layer from a single terminal holdout into a reproducible planning decision contract. The model is deliberately simple. The evidence standard is the upgrade.

## Why the old gate was insufficient

Earlier versions used one 28-point terminal holdout, weekly seasonal-naive forecasts and a single rule:

```text
MAPE <= 20%  -> approved
```

That checks absolute error, but it does not answer three important planning questions:

1. Was every prediction made with only information available at its forecast origin?
2. Does the candidate beat a simpler baseline that a product team could use with almost no modelling effort?
3. Is forecast uncertainty calibrated well enough to support planning rather than point estimates alone?

The v0.34 reference exposes why this matters. `photo_editor:dau` has low absolute error, but the simpler last-observation benchmark is better. A gate that only checks a 20% error threshold would approve a model that adds no forecasting value.

## Rolling-origin geometry

The current contract uses:

```text
season              = 7 days
forecast horizon    = 7 days
rolling origins     = 4
backtest points     = 28 per metric
candidate           = lag-7 weekly seasonal naive
benchmark           = last observation carried across the 7-day horizon
```

At each origin, every seasonal source date must be on or before the origin date. The implementation rejects `horizon_days > season`, because a longer direct horizon would require a seasonal source from inside the unseen holdout and would turn the backtest into a recursive or leakage-prone forecast without an explicit contract change.

The 28 points are therefore not one forecast generated with knowledge of the whole holdout. They are four separate seven-day plans, each built as of its own historical origin.

## Prediction intervals

For each origin, historical seasonal residuals are computed only from the training prefix:

```text
residual_t = y_t - y_(t-7)
```

The interval radius is the absolute-residual order statistic with rank

```text
ceil((n + 1) * (1 - alpha))
```

capped at `n`, with `alpha = 0.10` in the reference. This gives a nominal 90% marginal interval around each seasonal-naive point forecast.

The order statistic is explicit rather than delegated to a library interpolation default. This keeps generator and validator semantics stable across dependency versions.

The lower bound is clipped at zero because the reference metrics are non-negative counts or revenue totals.

## Non-compensatory planning gate

A metric is forecast-eligible only when every hard gate passes:

```text
backtest points >= 28
MAPE <= 20%
WAPE <= 20%
candidate WAPE <= last-observation benchmark WAPE
empirical interval coverage >= 85%
```

There is no weighted score. Very good interval coverage cannot compensate for poor point accuracy, and low absolute error cannot compensate for losing to the simpler benchmark.

WAPE is included because the planning use case often concerns aggregate volume or revenue and because daily count metrics can contain low values that make percentage errors unstable. MAPE remains reported for continuity with earlier project versions.

The 85% empirical coverage gate is an operating tolerance around the nominal 90% interval on a 28-point rolling backtest. It is not presented as a formal coverage theorem for future production forecasts.

## Reference outcome

Under `seed=2206`, `days=120`, the v0.34 decision is:

```text
approved    file_transfer:dau
approved    notes_app:dau
withheld    photo_editor:dau
withheld    all revenue_gbp metrics
withheld    all paid_subscription metrics
```

Headline WAPE evidence:

| Metric | Candidate WAPE | Benchmark WAPE | Decision |
|---|---:|---:|---|
| `file_transfer:dau` | 5.91% | 7.05% | approved |
| `notes_app:dau` | 3.97% | 4.64% | approved |
| `photo_editor:dau` | 3.92% | 2.56% | withheld: benchmark gate |

The photo-editor result is intentional. The candidate is accurate in absolute terms, but a simpler model is materially better on the declared backtest. The correct planning decision is therefore to withhold the candidate rather than lower the bar after seeing the result.

Revenue and subscription forecasts remain withheld primarily because their absolute accuracy exceeds the 20% MAPE/WAPE limits. Some also lose to the simpler benchmark.

## Plan-vs-actual reconciliation

Every historical seven-day origin produces a reconciliation row containing:

```text
origin date
forecast target start/end dates
candidate planned total
observed actual total
benchmark total
signed planning error
absolute percentage planning error
```

This turns forecasting from a model-evaluation table into a performance-tracking artifact: a product team can see what a plan said at the time and what was subsequently observed.

The project does **not** sum the seven marginal prediction intervals and label the result a 90% interval for the seven-day total. That would require a joint-error/dependence model that is not part of the current contract.

## Generated artifacts

```text
forecast_evaluations.csv
forecast_backtest.csv
forecast_reconciliation.csv
forecast_contract.json
```

`forecast_evaluations.csv` retains the established public filename but now contains the richer rolling-origin decision evidence.

`scripts/validate_forecast_plan.py` independently reconstructs every reference forecast from Gold metrics and the first-open observation boundary. It checks lag source dates, forecast points, benchmark values, interval radii, MAPE/WAPE, coverage, decision gates and plan-vs-actual totals. It also pins the deterministic reference to two approved metrics and verifies the `photo_editor:dau` benchmark counterexample.

## Claim boundary

The data, product scale and forecast history are synthetic. Approval means the reference metric passes this declared planning gate under the current deterministic evidence. It is not a production SLA, a guarantee of future accuracy, or evidence that the same model would be preferred after product dynamics change.

The model class is intentionally modest. A more complex model should only replace it if a leakage-safe rolling backtest demonstrates a decision-relevant improvement over both this candidate and the trivial benchmark without weakening the pre-specified gates.
