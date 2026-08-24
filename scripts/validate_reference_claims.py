from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import pandas as pd


REFERENCE_VERSION = "0.33.0"
REFERENCE_RAW_ROWS = 276_249
REFERENCE_REJECTED_ROWS = 589
REFERENCE_CERTIFIED_ROWS = 275_660
REFERENCE_FORECAST_APPROVED = 3
REFERENCE_FORECAST_WITHHELD = 6
REFERENCE_EXPERIMENT_USERS = 8_000
REFERENCE_REVENUE_EFFECT = 0.685080828553912
REFERENCE_REVENUE_CI_LOW = 0.5514297450276882
REFERENCE_REVENUE_CI_HIGH = 0.8187319120801357
REFERENCE_PAID_EFFECT = -0.016249999999999987
REFERENCE_PAID_CI_LOW = -0.03363352022846357
REFERENCE_PAID_CI_HIGH = 0.0011335202284635942
REFERENCE_GUARDRAIL_TARGET_PER_ARM = 6_393
REFERENCE_GUARDRAIL_ADDITIONAL_PER_ARM = 2_393
REFERENCE_COUNTERFACTUAL_TREATED_USERS = 150_000
REFERENCE_COUNTERFACTUAL_REVENUE = 102_762.1242830868
REFERENCE_COUNTERFACTUAL_REVENUE_LOW = 82_714.46175415323
REFERENCE_COUNTERFACTUAL_REVENUE_HIGH = 122_809.78681202036
REFERENCE_POINT_IN_TIME_WATERMARK = 48.0
REFERENCE_STABLE_WATERMARK = 96.0
REFERENCE_96H_REQUIRED_LATE_EVENTS = 2_733_153
REFERENCE_96H_REQUIRED_REVISION_CELLS = 2_011
REFERENCE_96H_EVIDENCE_DAYS = 1_330
REFERENCE_MANIFEST_ARTIFACTS = 44


def _close(actual: object, expected: float, tol: float = 1e-9) -> bool:
    return math.isclose(float(actual), float(expected), rel_tol=0.0, abs_tol=tol)


def validate_reference_claims(root: Path) -> list[str]:
    failures: list[str] = []
    required = [
        "reference_summary.json",
        "pricing_experiment_estimates.csv",
        "pricing_experiment_decision.json",
        "pricing_guardrail_evidence_plan.json",
        "pricing_impact_decision.json",
        "watermark_policy_decision.json",
        "watermark_stability_decision.json",
        "watermark_certification_decision.json",
        "watermark_evidence_plan.csv",
        "watermark_evidence_plan_contract.json",
        "watermark_evidence_plan_decision.json",
        "MANIFEST.json",
    ]
    if any(not (root / name).is_file() for name in required):
        return ["missing_reference_evidence"]

    summary = json.loads((root / "reference_summary.json").read_text(encoding="utf-8"))
    estimates = pd.read_csv(root / "pricing_experiment_estimates.csv")
    experiment_payload = json.loads((root / "pricing_experiment_decision.json").read_text(encoding="utf-8"))
    guardrail = json.loads((root / "pricing_guardrail_evidence_plan.json").read_text(encoding="utf-8"))
    impact = json.loads((root / "pricing_impact_decision.json").read_text(encoding="utf-8"))
    point = json.loads((root / "watermark_policy_decision.json").read_text(encoding="utf-8"))
    stable = json.loads((root / "watermark_stability_decision.json").read_text(encoding="utf-8"))
    certified = json.loads((root / "watermark_certification_decision.json").read_text(encoding="utf-8"))
    evidence_plan = pd.read_csv(root / "watermark_evidence_plan.csv")
    evidence_contract = json.loads((root / "watermark_evidence_plan_contract.json").read_text(encoding="utf-8"))
    evidence_decision = json.loads((root / "watermark_evidence_plan_decision.json").read_text(encoding="utf-8"))
    manifest = json.loads((root / "MANIFEST.json").read_text(encoding="utf-8"))

    if summary.get("version") != REFERENCE_VERSION:
        failures.append("reference_summary_version")
    quality = summary.get("quality", {})
    if int(quality.get("rows_raw", -1)) != REFERENCE_RAW_ROWS:
        failures.append("reference_raw_rows")
    if int(quality.get("rows_rejected", -1)) != REFERENCE_REJECTED_ROWS:
        failures.append("reference_rejected_rows")
    if int(quality.get("rows_certified", -1)) != REFERENCE_CERTIFIED_ROWS:
        failures.append("reference_certified_rows")

    forecast_gate = summary.get("forecast_gate", {})
    if int(forecast_gate.get("approved", -1)) != REFERENCE_FORECAST_APPROVED:
        failures.append("reference_forecast_approved")
    if int(forecast_gate.get("withheld", -1)) != REFERENCE_FORECAST_WITHHELD:
        failures.append("reference_forecast_withheld")

    experiment_summary = summary.get("pricing_experiment", {})
    integrity = experiment_summary.get("integrity", {})
    decision = experiment_payload.get("decision", {})
    if int(integrity.get("n_total", -1)) != REFERENCE_EXPERIMENT_USERS:
        failures.append("reference_experiment_users")
    if int(integrity.get("n_control", -1)) != 4_000 or int(integrity.get("n_treatment", -1)) != 4_000:
        failures.append("reference_experiment_allocation")
    if not _close(integrity.get("p_value", -1), 1.0, tol=1e-15):
        failures.append("reference_srm_pvalue")
    if decision.get("action") != "hold":
        failures.append("reference_experiment_action")
    if decision.get("assignment_integrity_gate") is not True or decision.get("revenue_gate") is not True:
        failures.append("reference_experiment_positive_gates")
    if decision.get("paid_guardrail_gate") is not False:
        failures.append("reference_paid_guardrail_gate")

    by_metric = {row["metric"]: row for _, row in estimates.iterrows()}
    revenue = by_metric.get("revenue_gbp_30d")
    paid = by_metric.get("paid_subscription_30d")
    if revenue is None or paid is None:
        failures.append("reference_experiment_estimates_missing")
    else:
        for name, actual, expected in [
            ("reference_revenue_effect", revenue["effect"], REFERENCE_REVENUE_EFFECT),
            ("reference_revenue_ci_low", revenue["ci_low"], REFERENCE_REVENUE_CI_LOW),
            ("reference_revenue_ci_high", revenue["ci_high"], REFERENCE_REVENUE_CI_HIGH),
            ("reference_paid_effect", paid["effect"], REFERENCE_PAID_EFFECT),
            ("reference_paid_ci_low", paid["ci_low"], REFERENCE_PAID_CI_LOW),
            ("reference_paid_ci_high", paid["ci_high"], REFERENCE_PAID_CI_HIGH),
        ]:
            if not _close(actual, expected, tol=1e-12):
                failures.append(name)

    if int(guardrail.get("equal_allocation_target_per_arm", -1)) != REFERENCE_GUARDRAIL_TARGET_PER_ARM:
        failures.append("reference_guardrail_target_per_arm")
    if int(guardrail.get("additional_users_per_arm_from_current_minimum", -1)) != REFERENCE_GUARDRAIL_ADDITIONAL_PER_ARM:
        failures.append("reference_guardrail_additional_per_arm")
    if guardrail.get("status") != "additional_evidence_required":
        failures.append("reference_guardrail_evidence_status")

    if impact.get("planning_status") != "counterfactual_only":
        failures.append("reference_impact_planning_status")
    if impact.get("decision_authorised_rollout") is not False:
        failures.append("reference_impact_authorisation")
    if int(impact.get("authorised_treated_users", -1)) != 0:
        failures.append("reference_authorised_treated_users")
    if impact.get("authorised_incremental_revenue_gbp") is not None:
        failures.append("reference_authorised_revenue_should_be_null")
    if int(impact.get("counterfactual_treated_users", -1)) != REFERENCE_COUNTERFACTUAL_TREATED_USERS:
        failures.append("reference_counterfactual_treated_users")
    for name, key, expected in [
        ("reference_counterfactual_revenue", "counterfactual_incremental_revenue_gbp", REFERENCE_COUNTERFACTUAL_REVENUE),
        ("reference_counterfactual_revenue_low", "counterfactual_incremental_revenue_ci_low_gbp", REFERENCE_COUNTERFACTUAL_REVENUE_LOW),
        ("reference_counterfactual_revenue_high", "counterfactual_incremental_revenue_ci_high_gbp", REFERENCE_COUNTERFACTUAL_REVENUE_HIGH),
    ]:
        if not _close(impact.get(key, -1), expected, tol=1e-6):
            failures.append(name)

    if float(point.get("selected_lateness_hours", -1)) != REFERENCE_POINT_IN_TIME_WATERMARK:
        failures.append("reference_point_in_time_watermark")
    if float(stable.get("selected_lateness_hours", -1)) != REFERENCE_STABLE_WATERMARK:
        failures.append("reference_stable_watermark")
    if certified.get("status") != "no_candidate_certified_familywise_95" or certified.get("selected_lateness_hours") is not None:
        failures.append("reference_certification_status")

    plan96 = evidence_plan.loc[evidence_plan["allowed_lateness_hours"].astype(float).eq(96.0)]
    if len(plan96) != 1:
        failures.append("reference_96h_evidence_row")
    else:
        row96 = plan96.iloc[0]
        if int(row96["required_late_event_trials"]) != REFERENCE_96H_REQUIRED_LATE_EVENTS:
            failures.append("reference_96h_required_late_events")
        if int(row96["required_revised_metric_cells"]) != REFERENCE_96H_REQUIRED_REVISION_CELLS:
            failures.append("reference_96h_required_revision_cells")
        if int(row96["estimated_calendar_days_for_both_proportions"]) != REFERENCE_96H_EVIDENCE_DAYS:
            failures.append("reference_96h_evidence_days")
        if str(row96["evidence_only_addressable"]).lower() != "true":
            failures.append("reference_96h_evidence_only")
    if evidence_contract.get("global_monotonic_threshold_claimed") is not False:
        failures.append("reference_global_monotonic_claim")
    if float(evidence_decision.get("selected_lateness_hours", -1)) != 96.0:
        failures.append("reference_evidence_plan_selected_watermark")

    if int(manifest.get("artifact_count", -1)) != REFERENCE_MANIFEST_ARTIFACTS:
        failures.append("reference_manifest_artifact_count")

    return failures


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate pinned deterministic v0.33 reference claims")
    parser.add_argument("root", nargs="?", default="build/reference")
    args = parser.parse_args()
    failures = validate_reference_claims(Path(args.root))
    if failures:
        raise SystemExit("Reference-claim validation failed: " + ", ".join(failures))
    print(f"Reference-claim validation passed: {args.root}")


if __name__ == "__main__":
    main()