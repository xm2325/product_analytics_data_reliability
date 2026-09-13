# Decision log

Validated against GitHub Actions run from commit `98336ea30c93a5a3909fe4ddcfdf497cb7f2b4e5` on 13 September 2026.

## Release decision 1 — cancellation model

**Candidates:** calibrated Logistic Regression and calibrated histogram gradient boosting (HGB).

**Selection data:** validation period only. The final future test is not used to choose the champion.

Validation results:

| Model | ROC-AUC | Average precision | Brier |
|---|---:|---:|---:|
| Logistic Regression | 0.861 | 0.822 | 0.143 |
| HGB | 0.881 | 0.841 | 0.134 |

The pre-set gate requires HGB to improve validation average precision by at least 0.01 and not worsen Brier by more than 0.005. HGB passes and becomes the champion before the test period is examined.

Future test:

| Model | ROC-AUC | Average precision | Brier |
|---|---:|---:|---:|
| Logistic Regression | 0.821 | 0.685 | 0.158 |
| HGB | 0.839 | 0.708 | 0.159 |

**Decision:** HGB remains the selected model, but it is immediately subject to the later-period health check below. The test result is used for evaluation/monitoring, not retrospective model selection.

## Release decision 2 — later-period health

Future-period checks for the selected cancellation model:

- max PSI: **0.463** (lead time is the largest shift);
- ADR PSI: **0.366**;
- Brier: **0.134 validation → 0.159 test** (`+0.025`);
- cancellation-adjusted gross-value proxy error: **-12.5%**.

The review rule triggers if max PSI exceeds 0.15, Brier worsens by more than 0.015, or absolute gross-value proxy error exceeds 5%.

**Decision: REVIEW / RECALIBRATION ASSESSMENT REQUIRED.**

The correct action is not to silently retrain. First check feature/process changes, probability calibration, source timing, policy changes and whether a new training window is representative.

## Release decision 3 — policy-sensitive cancellation feature

Removing `deposit_type` reduces Logistic Regression future-test average precision from **0.685** to **0.652**, a drop of **0.033**.

The top 10% cancellation rate without deposit type is still **80.6%**, compared with **84.5%** for the selected full HGB model.

**Decision:** keep the full benchmark for this public-data experiment, but make dependency on deposit policy explicit. In a real marketplace, validate stability before using such a feature because a commercial-policy change can alter its meaning quickly.

## Release decision 4 — weekly demand forecast

Pre-test validation selects Ridge over HGB among the complex candidates:

| Candidate | Validation WAPE |
|---|---:|
| Ridge | 13.9% |
| HGB | 17.8% |

Future test:

| Forecast | WAPE |
|---|---:|
| 4-week rolling mean | **8.5%** |
| Seasonal lag-52 | 12.1% |
| selected Ridge | 12.6% |

The release rule requires at least 2% relative WAPE improvement over the best simple baseline.

**Decision: DO NOT PROMOTE RIDGE. Keep the 4-week rolling baseline.**

This is a useful result: a senior model-review process should reject an unnecessary ML model.

## Release decision 5 — booking-ADR reference

The median ADR reference has future-test MAE **24.71 ADR units**.

The split-conformal central-50% interval covers:

- **46.9%** of the validation period;
- **39.8%** of the future test period.

Future under-coverage indicates distribution movement and/or model misspecification.

**Decision: ANALYST REFERENCE ONLY. Do not use the band as an automated pricing rule.**

No causal claim is made about price elasticity or incremental revenue.

## Release decision 6 — UK market audit

A one-time Greater Manchester Inside Airbnb audit was run separately. The source calendar cannot distinguish bookings from host-blocked unavailable nights. In the audited snapshot, asking price was also effectively static within listing over the forward calendar in the fields used.

**Decision:** retain the UK source as market/supply context and a data-quality example, but do not turn it into a booking label or dynamic-price training set.

## Overall project decision

The project is ready as a technical portfolio case because the workflow now shows both model wins and model refusals. For a real holiday-rental production system, first-party booking, inventory, quote, search and experiment data would be required before moving from this public benchmark to live pricing, personalisation or ranking decisions.
