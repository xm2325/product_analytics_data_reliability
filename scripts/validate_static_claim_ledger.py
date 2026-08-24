from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import pandas as pd


REFERENCE_TEST_COUNT = 68


def _fail(message: str) -> None:
    raise SystemExit(f"Static-claim validation failed: {message}")


def _as_float(claims: dict[str, str], name: str) -> float:
    try:
        return float(claims[name])
    except (KeyError, ValueError) as exc:
        raise SystemExit(f"Static-claim validation failed: invalid or missing {name}") from exc


def _assert_close(claims: dict[str, str], name: str, expected: float, tol: float = 1e-6) -> None:
    actual = _as_float(claims, name)
    if not math.isclose(actual, float(expected), rel_tol=0.0, abs_tol=tol):
        _fail(f"{name}: expected {expected}, got {actual}")


def _assert_text(claims: dict[str, str], name: str, expected: str) -> None:
    if claims.get(name) != expected:
        _fail(f"{name}: expected {expected!r}, got {claims.get(name)!r}")


def validate(root: Path, ledger_path: Path) -> None:
    ledger = pd.read_csv(ledger_path, dtype=str, keep_default_na=False)
    required_columns = {"claim", "value", "unit", "context", "interpretation_limit"}
    if set(ledger.columns) != required_columns:
        _fail(f"unexpected ledger columns: {list(ledger.columns)}")
    if ledger["claim"].duplicated().any():
        duplicates = sorted(ledger.loc[ledger["claim"].duplicated(), "claim"].unique())
        _fail(f"duplicate claims: {duplicates}")
    if ledger[list(required_columns)].eq("").any().any():
        _fail("ledger contains blank required fields")
    if not ledger["context"].str.startswith("v0.33").all():
        stale = ledger.loc[~ledger["context"].str.startswith("v0.33"), ["claim", "context"]]
        _fail(f"stale context rows: {stale.to_dict(orient='records')}")

    claims = dict(zip(ledger["claim"], ledger["value"], strict=True))
    summary = json.loads((root / "reference_summary.json").read_text(encoding="utf-8"))
    manifest = json.loads((root / "MANIFEST.json").read_text(encoding="utf-8"))
    impact = summary["pricing_impact_planning"]
    experiment = summary["pricing_experiment"]
    estimates = {row["metric"]: row for row in experiment["estimates"]}
    processing = summary["processing_time"]

    if summary.get("version") != "0.33.0":
        _fail(f"generated summary version is {summary.get('version')}, not 0.33.0")

    quality = summary["quality"]
    for name in ("rows_raw", "rows_rejected", "rows_certified"):
        if int(_as_float(claims, name)) != int(quality[name]):
            _fail(f"{name} differs from generated quality evidence")

    forecast_gate = summary["forecast_gate"]
    if int(_as_float(claims, "forecast_approved")) != int(forecast_gate["approved"]):
        _fail("forecast_approved differs from generated evidence")
    if int(_as_float(claims, "forecast_withheld")) != int(forecast_gate["withheld"]):
        _fail("forecast_withheld differs from generated evidence")

    integrity = experiment["integrity"]
    revenue = estimates["revenue_gbp_30d"]
    paid = estimates["paid_subscription_30d"]
    decision = experiment["decision"]
    if int(_as_float(claims, "pricing_experiment_users")) != int(integrity["n_total"]):
        _fail("pricing_experiment_users differs from generated experiment")
    if int(_as_float(claims, "pricing_experiment_control")) != int(integrity["n_control"]):
        _fail("pricing_experiment_control differs from generated experiment")
    if int(_as_float(claims, "pricing_experiment_treatment")) != int(integrity["n_treatment"]):
        _fail("pricing_experiment_treatment differs from generated experiment")
    _assert_close(claims, "pricing_experiment_srm_pvalue", integrity["p_value"], tol=1e-12)
    _assert_close(claims, "pricing_experiment_revenue_effect", revenue["effect"], tol=1e-9)
    _assert_close(claims, "pricing_experiment_revenue_ci_low", revenue["ci_low"], tol=1e-9)
    _assert_close(claims, "pricing_experiment_revenue_ci_high", revenue["ci_high"], tol=1e-9)
    _assert_close(claims, "pricing_experiment_paid_effect_pp", 100.0 * paid["effect"], tol=1e-6)
    _assert_close(claims, "pricing_experiment_paid_ci_low_pp", 100.0 * paid["ci_low"], tol=1e-6)
    _assert_close(claims, "pricing_experiment_paid_ci_high_pp", 100.0 * paid["ci_high"], tol=1e-6)
    _assert_close(claims, "pricing_experiment_paid_harm_margin_pp", 100.0 * experiment["contract"]["paid_harm_guardrail"], tol=1e-12)
    _assert_text(claims, "pricing_experiment_action", decision["action"])

    evidence = impact["guardrail_evidence"]
    impact_decision = impact["decision"]
    if int(_as_float(claims, "guardrail_target_per_arm")) != int(evidence["equal_allocation_target_per_arm"]):
        _fail("guardrail_target_per_arm differs from generated plan")
    if int(_as_float(claims, "guardrail_additional_per_arm")) != int(evidence["additional_users_per_arm_from_current_minimum"]):
        _fail("guardrail_additional_per_arm differs from generated plan")
    _assert_text(claims, "guardrail_evidence_status", evidence["status"])
    _assert_text(claims, "impact_planning_status", impact_decision["planning_status"])
    _assert_text(claims, "impact_decision_authorised_rollout", str(bool(impact_decision["decision_authorised_rollout"])).lower())
    if int(_as_float(claims, "impact_counterfactual_treated_users")) != int(impact_decision["counterfactual_treated_users"]):
        _fail("impact_counterfactual_treated_users differs")
    _assert_close(claims, "impact_counterfactual_revenue_gbp", impact_decision["counterfactual_incremental_revenue_gbp"], tol=1e-6)
    _assert_close(claims, "impact_counterfactual_revenue_ci_low_gbp", impact_decision["counterfactual_incremental_revenue_ci_low_gbp"], tol=1e-6)
    _assert_close(claims, "impact_counterfactual_revenue_ci_high_gbp", impact_decision["counterfactual_incremental_revenue_ci_high_gbp"], tol=1e-6)
    if int(_as_float(claims, "impact_authorised_treated_users")) != int(impact_decision["authorised_treated_users"]):
        _fail("impact_authorised_treated_users differs")
    expected_authorised_revenue = "none" if impact_decision["authorised_incremental_revenue_gbp"] is None else str(impact_decision["authorised_incremental_revenue_gbp"])
    _assert_text(claims, "impact_authorised_revenue_gbp", expected_authorised_revenue)

    point = processing["point_in_time_watermark_calibration"]
    stable = processing["watermark_stability_decision"]
    certified = processing["watermark_certification_decision"]
    plan = {float(row["allowed_lateness_hours"]): row for row in processing["watermark_evidence_plan"]}
    plan_decision = processing["watermark_evidence_plan_decision"]
    contract = processing["watermark_evidence_plan_contract"]
    _assert_close(claims, "point_in_time_selected_watermark", point["selected_lateness_hours"], tol=1e-12)
    _assert_close(claims, "stable_selected_watermark", stable["selected_lateness_hours"], tol=1e-12)
    _assert_text(claims, "certification_status", certified["status"])
    _assert_text(claims, "certified_watermark", "none" if certified["selected_lateness_hours"] is None else str(certified["selected_lateness_hours"]))
    _assert_close(claims, "evidence_plan_selected_watermark", plan_decision["selected_lateness_hours"], tol=1e-12)
    row96 = plan[96.0]
    for name, expected in {
        "evidence_plan_96h_required_late_trials": row96["required_late_event_trials"],
        "evidence_plan_96h_required_revised_cells": row96["required_revised_metric_cells"],
        "evidence_plan_96h_combined_days": row96["estimated_calendar_days_for_both_proportions"],
        "evidence_plan_96h_combined_years": row96["estimated_calendar_years_for_both_proportions"],
    }.items():
        _assert_close(claims, name, expected, tol=1e-4 if name.endswith("years") else 1e-9)
    _assert_text(claims, "global_monotonic_threshold_claimed", str(bool(contract["global_monotonic_threshold_claimed"])).lower())

    if int(_as_float(claims, "unit_tests")) != REFERENCE_TEST_COUNT:
        _fail(f"unit_tests must be pinned to {REFERENCE_TEST_COUNT}")
    if int(_as_float(claims, "manifest_artifacts")) != int(manifest["artifact_count"]):
        _fail("manifest_artifacts differs from generated manifest")

    print(f"Static-claim validation passed: {ledger_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate checked-in public v0.33 claims against generated reference evidence")
    parser.add_argument("root", nargs="?", default="build/reference")
    parser.add_argument("--ledger", default="results/reference_summary.csv")
    args = parser.parse_args()
    validate(Path(args.root), Path(args.ledger))


if __name__ == "__main__":
    main()