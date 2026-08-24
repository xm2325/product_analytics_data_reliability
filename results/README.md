# Reference and planning results

This directory contains the current deterministic headline claim ledger plus preserved historical planning context.

## Current deterministic reference

The current reference is **v0.33** with `seed=2206`, `days=120`.

The authoritative full build is the generated `reference-evidence` GitHub Actions artifact. It contains CSV/JSON evidence, `workbench.duckdb`, and `MANIFEST.json`. The checked-in `reference_summary.csv` is intentionally smaller than the full evidence bundle: it pins the headline claims that define the public decision story and is validated against the generated reference in CI.

## Product experiment decision

The controlled pricing experiment remains exactly 4,000 control and 4,000 treatment users.

```text
SRM p-value                   = 1.000
revenue effect                = +£0.6851 per user / 30d
revenue 95% CI                = [£0.5514, £0.8187]
paid-conversion effect        = -1.625 percentage points
paid-conversion 95% CI        = [-3.363, +0.113] percentage points
paid harm margin              = -3.000 percentage points
final action                  = HOLD
```

The experiment passes assignment integrity and the revenue primary gate. It does **not** pass the paid-conversion non-inferiority guardrail: the point estimate remains inside the -3pp harm margin, but the lower confidence bound crosses it. Revenue is not allowed to compensate for the failed guardrail.

Generated experiment evidence:

```text
pricing_experiment_users.csv
pricing_experiment_estimates.csv
pricing_experiment_contract.json
pricing_experiment_decision.json
```

`scripts/validate_pricing_experiment.py` independently recomputes SRM, ANCOVA + HC3 revenue uncertainty, paid-conversion uncertainty and the final gate state from the user-level artifact.

## v0.33 decision-aware impact planning

v0.33 asks two separate questions after the experiment result:

1. If the current 30-day revenue effect were applied to a fixed synthetic launch ramp, what counterfactual impact would it imply?
2. Does the experiment decision actually authorise that rollout?

The synthetic launch scenario contains three 100,000-user eligible cohorts with hypothetical adoption shares of 25%, 50% and 75%:

```text
hypothetical treated users           = 25,000 + 50,000 + 75,000
                                      = 150,000
counterfactual incremental revenue   = £102,762.12
95% interval                         = [£82,714.46, £122,809.79]
```

Each cohort contributes only its first 30-day revenue outcome. This is **not** a 90-day LTV extrapolation and does not assume the 30-day effect persists beyond its measured horizon.

The experiment is still HOLD, so the decision-aware output remains:

```text
planning_status                 = counterfactual_only
decision_authorised_rollout     = false
authorised_treated_users        = 0
authorised_incremental_revenue  = null
```

A positive counterfactual revenue scenario is therefore visible for planning but is not represented as an authorised or realised impact claim.

### Conditional paid-guardrail evidence target

The current paid-conversion lower bound is recomputed with the same `ddof=1` variance convention used by the experiment. Under the explicit planning assumption that observed arm rates remain representative, the first equal-allocation arm size whose projected lower bound is strictly above the -3pp harm margin is:

```text
current users per arm      = 4,000
conditional target per arm = 6,393
additional per arm         = 2,393
```

The integer boundary is audited directly: 6,393 passes the projected rule and 6,392 does not.

This is a conditional evidence target, not a power guarantee. If future conversion rates move, the required sample size moves too. If the observed point estimate itself falls to or below -3pp, the planner returns a structural point-estimate failure rather than claiming more sample can repair the result.

Generated impact evidence:

```text
pricing_impact_scenario.csv
pricing_impact_contract.json
pricing_guardrail_evidence_plan.json
pricing_impact_decision.json
```

`scripts/validate_impact_plan.py` independently recomputes the current paid-conversion CI, the 6,393/6,392 boundary, the launch-ramp volumes, counterfactual revenue scaling and the HOLD-aware authorisation state.

See `docs/IMPACT_PLANNING.md` and `docs/EXPERIMENT_DECISIONING.md`.

## Freshness evidence ladder

Freshness evidence remains separated into four decision strengths:

```text
48h  = Apr-30 shortest point-in-time feasible candidate
96h  = shortest candidate observed feasible in all 9 rolling windows
none = family-wise 95% statistically certified candidate
96h  = only candidate whose remaining gap is evidence-depth-only
```

These statements are not interchangeable.

## Cycle-stable certification evidence plan

The unchanged risk budget and 72-bound family are carried through uncertainty analysis and evidence planning. v0.31 introduced cycle-stable exact evidence targets; v0.33 keeps that contract unchanged.

| Candidate | Planning classification | Key evidence |
|---|---|---|
| 24h | not evidence-only | late/revised rates and £23.98 revenue maximum already breach budgets |
| 48h | not evidence-only | revised-cell rate 1.288% and £11.99 revenue maximum breach budgets; late target 99,573,018 |
| 72h | not evidence-only | £11.99 revenue maximum breach; late requirement exceeds 100M search cap; revised target 14,989 |
| 96h | **evidence-depth-only** | point rates and deterministic maxima pass |

For 96h:

```text
required finalizable-event trials  = 2,733,153
late-event audited cycle            = 206
required finalized KPI cells       = 2,011
revised-cell audited cycle          = 333
estimated late-bound depth          = 1,330 days
estimated revised-cell depth        = 224 days
combined planning depth             = 1,330 days (~3.64 years)
global_monotonic_threshold_claimed  = false
```

These are conditional evidence-depth estimates under fixed planning rates and throughput, not a guarantee that waiting that many additional wall-clock days will certify the policy.

## Point-in-time and rolling evidence

For each 24/48/72/96-hour candidate, the late-event decision denominator contains only events whose event date is on or before that candidate's watermark. At the final 2026-04-30 snapshot, 48h is the shortest point-estimate feasible candidate.

Across nine weekly snapshots:

| Candidate | Observed feasible windows | Observed stable? |
|---|---:|---|
| 24h | 0 / 9 | No |
| 48h | 5 / 9 | No |
| 72h | 8 / 9 | No |
| 96h | **9 / 9** | **Yes** |

The per-window shortest-feasible sequence is `72,72,72,96,48,48,48,48,48` hours.

## Uncertainty certification

The uncertainty layer uses one-sided exact Clopper–Pearson upper bounds for the late-event and revised-KPI-cell proportions. Four candidates × nine windows × two proportional constraints gives **72 simultaneous bounds** under a 95% family-wise Bonferroni correction.

| Candidate | Certified windows | Worst late upper | Worst revised-cell upper |
|---|---:|---:|---:|
| 24h | 0 / 9 | 7.1543% | 4.5588% |
| 48h | 0 / 9 | 0.5601% | 3.5722% |
| 72h | 0 / 9 | 0.5612% | 2.4904% |
| 96h | **0 / 9** | **0.5485%** | **1.7385%** |

The family-wise decision remains:

```text
status = no_candidate_certified_familywise_95
selected_lateness_hours = null
```

This is an insufficient-evidence result, not evidence that 96h is unsafe. Maximum revenue and paid-subscription revisions remain deterministic hard gates.

## Earlier processing-time and retention evidence

The row-level/metric-level late-arrival audit remains part of the current build, including late-event exceptions, settled-vs-snapshot KPI revisions and idempotent keyed backfill evidence. Retention also remains point-in-time: only cohorts whose target date is on or before `analysis_as_of` enter D7/D30 denominators.

## Preserved historical context

`risk_aware_design.csv` is a preserved pre-v0.23 planning snapshot from a broader unequal-randomisation study. It is methodological context rather than a current-workflow regression target or production recommendation.

## Reproduce the current reference

```bash
make check
```

or run the gates separately:

```bash
make reference
python scripts/validate_build.py build/reference
python scripts/validate_watermark_backtest.py build/reference
python scripts/validate_uncertainty_certification.py build/reference
python scripts/validate_evidence_plan.py build/reference
python scripts/validate_pricing_experiment.py build/reference
python scripts/validate_impact_plan.py build/reference
python scripts/validate_reference_claims.py build/reference
python scripts/validate_static_claim_ledger.py build/reference
```

See `docs/IMPACT_PLANNING.md`, `docs/EXPERIMENT_DECISIONING.md`, `docs/WATERMARK_CALIBRATION.md`, `docs/WATERMARK_STABILITY.md`, `docs/WATERMARK_UNCERTAINTY.md`, `docs/CERTIFICATION_EVIDENCE_PLANNING.md`, `docs/LATE_ARRIVAL_GOVERNANCE.md`, and `docs/REPRODUCIBILITY.md`.