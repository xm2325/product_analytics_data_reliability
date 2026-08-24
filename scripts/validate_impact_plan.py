from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import pandas as pd
from scipy.stats import norm


REFERENCE_TARGET_PER_ARM = 6393
REFERENCE_ADDITIONAL_PER_ARM = 2393
REFERENCE_COUNTERFACTUAL_TREATED_USERS = 150_000


def _fail(message: str) -> None:
    raise SystemExit(f"Impact-plan validation failed: {message}")


def _close(actual: float, expected: float, tol: float = 1e-9) -> bool:
    return math.isclose(float(actual), float(expected), rel_tol=0.0, abs_tol=tol)


def _projected_lower(p_control: float, p_treatment: float, n_per_arm: int, z: float) -> float:
    variance_sum = p_control * (1.0 - p_control) + p_treatment * (1.0 - p_treatment)
    return (p_treatment - p_control) - z * math.sqrt(variance_sum / (n_per_arm - 1))


def validate(root: Path) -> None:
    required = [
        "pricing_experiment_users.csv",
        "pricing_experiment_estimates.csv",
        "pricing_experiment_decision.json",
        "pricing_impact_scenario.csv",
        "pricing_impact_contract.json",
        "pricing_guardrail_evidence_plan.json",
        "pricing_impact_decision.json",
        "reference_summary.json",
    ]
    missing = [name for name in required if not (root / name).is_file()]
    if missing:
        _fail(f"missing artifacts: {missing}")

    users = pd.read_csv(root / "pricing_experiment_users.csv")
    estimates = pd.read_csv(root / "pricing_experiment_estimates.csv")
    experiment_payload = json.loads((root / "pricing_experiment_decision.json").read_text(encoding="utf-8"))
    scenario = pd.read_csv(root / "pricing_impact_scenario.csv")
    contract = json.loads((root / "pricing_impact_contract.json").read_text(encoding="utf-8"))
    evidence = json.loads((root / "pricing_guardrail_evidence_plan.json").read_text(encoding="utf-8"))
    impact = json.loads((root / "pricing_impact_decision.json").read_text(encoding="utf-8"))
    summary = json.loads((root / "reference_summary.json").read_text(encoding="utf-8"))

    # The impact contract is versioned independently from the top-level workbench release.
    # Validate its evidence and invariants rather than pinning this validator to v0.33 forever.
    if not str(summary.get("version", "")).strip():
        _fail("reference summary version missing")
    if contract.get("no_ltv_extrapolation") is not True or contract.get("no_effect_persistence_beyond_30d_assumed") is not True:
        _fail("long-horizon extrapolation boundary is not explicit")
    if contract.get("synthetic_scale_only") is not True:
        _fail("synthetic scale boundary missing")
    if contract.get("eligible_users_per_cohort") != [100000, 100000, 100000]:
        _fail("eligible-user scenario changed")
    if contract.get("hypothetical_adoption_shares") != [0.25, 0.5, 0.75]:
        _fail("adoption scenario changed")

    if len(scenario) != 3:
        _fail("expected three launch cohorts")
    expected_treated = [25000, 50000, 75000]
    if scenario["hypothetical_treated_users"].astype(int).tolist() != expected_treated:
        _fail("cohort treated-user ramp changed")

    revenue_rows = estimates.loc[estimates["metric"].eq("revenue_gbp_30d")]
    paid_rows = estimates.loc[estimates["metric"].eq("paid_subscription_30d")]
    if len(revenue_rows) != 1 or len(paid_rows) != 1:
        _fail("experiment estimate rows missing or duplicated")
    revenue = revenue_rows.iloc[0]
    paid = paid_rows.iloc[0]
    for column, source in [
        ("revenue_effect_gbp_per_user_30d", "effect"),
        ("revenue_effect_ci_low_gbp_per_user_30d", "ci_low"),
        ("revenue_effect_ci_high_gbp_per_user_30d", "ci_high"),
    ]:
        if not all(_close(value, revenue[source], tol=1e-12) for value in scenario[column]):
            _fail(f"{column} does not come from experiment evidence")

    treated_total = int(scenario["hypothetical_treated_users"].sum())
    if treated_total != REFERENCE_COUNTERFACTUAL_TREATED_USERS:
        _fail("counterfactual treated-user total changed")
    expected_revenue = treated_total * float(revenue["effect"])
    expected_low = treated_total * float(revenue["ci_low"])
    expected_high = treated_total * float(revenue["ci_high"])
    if not _close(scenario["counterfactual_incremental_revenue_gbp"].sum(), expected_revenue, tol=1e-6):
        _fail("counterfactual revenue sum does not scale experiment effect")
    if not _close(scenario["counterfactual_incremental_revenue_ci_low_gbp"].sum(), expected_low, tol=1e-6):
        _fail("counterfactual revenue lower bound mismatch")
    if not _close(scenario["counterfactual_incremental_revenue_ci_high_gbp"].sum(), expected_high, tol=1e-6):
        _fail("counterfactual revenue upper bound mismatch")

    assignment = pd.to_numeric(users["treatment"], errors="raise").astype(int)
    response = pd.to_numeric(users["paid_subscription_30d"], errors="raise").astype(int)
    control = response.loc[assignment.eq(0)]
    treated = response.loc[assignment.eq(1)]
    if len(control) != 4000 or len(treated) != 4000:
        _fail("reference experiment arm sizes changed")
    p_control = float(control.mean())
    p_treatment = float(treated.mean())
    difference = p_treatment - p_control
    z = float(norm.ppf(0.975))
    current_se = math.sqrt(float(control.var(ddof=1) / len(control) + treated.var(ddof=1) / len(treated)))
    current_low = difference - z * current_se
    if not _close(current_low, paid["ci_low"], tol=1e-12):
        _fail("guardrail evidence plan does not share experiment CI definition")
    if not _close(evidence["current_ci_low"], current_low, tol=1e-12):
        _fail("stored current guardrail lower bound mismatch")
    if evidence.get("status") != "additional_evidence_required":
        _fail("reference guardrail evidence status changed")

    margin = float(evidence["harm_margin"])
    target = int(evidence["equal_allocation_target_per_arm"])
    if target != REFERENCE_TARGET_PER_ARM:
        _fail(f"target per arm changed: {target}")
    if int(evidence["additional_users_per_arm_from_current_minimum"]) != REFERENCE_ADDITIONAL_PER_ARM:
        _fail("additional per-arm evidence changed")
    if _projected_lower(p_control, p_treatment, target, z) <= margin:
        _fail("reported target does not clear guardrail")
    if _projected_lower(p_control, p_treatment, target - 1, z) > margin:
        _fail("reported target is not the minimum integer boundary")

    experiment_decision = experiment_payload["decision"]
    if experiment_decision.get("action") != "hold":
        _fail("reference experiment is no longer HOLD")
    if impact.get("experiment_action") != "hold" or impact.get("planning_status") != "counterfactual_only":
        _fail("HOLD experiment did not remain counterfactual-only")
    if impact.get("decision_authorised_rollout") is not False:
        _fail("HOLD experiment incorrectly authorised rollout")
    if int(impact.get("authorised_treated_users", -1)) != 0:
        _fail("HOLD experiment authorised treated users")
    if impact.get("authorised_incremental_revenue_gbp") is not None:
        _fail("HOLD experiment has an authorised revenue impact claim")
    if int(impact.get("counterfactual_treated_users", -1)) != treated_total:
        _fail("impact summary treated-user total mismatch")
    if not _close(impact["counterfactual_incremental_revenue_gbp"], expected_revenue, tol=1e-6):
        _fail("impact summary counterfactual revenue mismatch")

    summary_impact = summary.get("pricing_impact_planning", {})
    if summary_impact.get("decision", {}).get("planning_status") != "counterfactual_only":
        _fail("reference summary impact decision missing")
    if int(summary_impact.get("guardrail_evidence", {}).get("equal_allocation_target_per_arm", -1)) != target:
        _fail("reference summary guardrail target mismatch")

    print(f"Impact-plan validation passed: {root}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate decision-aware pricing impact planning")
    parser.add_argument("root", nargs="?", default="build/reference")
    args = parser.parse_args()
    validate(Path(args.root))


if __name__ == "__main__":
    main()
