from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import pandas as pd


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


def validate(root: Path, ledger_path: Path) -> None:
    ledger = pd.read_csv(ledger_path, dtype=str, keep_default_na=False)
    required_columns = {"claim", "value", "unit", "context", "interpretation_limit"}
    if set(ledger.columns) != required_columns:
        _fail(f"unexpected ledger columns: {list(ledger.columns)}")
    if ledger["claim"].duplicated().any():
        duplicates = sorted(ledger.loc[ledger["claim"].duplicated(), "claim"].unique())
        _fail(f"duplicate claims: {duplicates}")
    if ledger[["claim", "value", "unit", "context", "interpretation_limit"]].eq("").any().any():
        _fail("ledger contains blank required fields")
    if not ledger["context"].str.startswith("v0.32").all():
        stale = ledger.loc[~ledger["context"].str.startswith("v0.32"), ["claim", "context"]]
        _fail(f"stale context rows: {stale.to_dict(orient='records')}")

    claims = dict(zip(ledger["claim"], ledger["value"], strict=True))
    summary = json.loads((root / "reference_summary.json").read_text(encoding="utf-8"))
    manifest = json.loads((root / "MANIFEST.json").read_text(encoding="utf-8"))
    experiment = summary["pricing_experiment"]
    estimates = {row["metric"]: row for row in experiment["estimates"]}
    revenue = estimates["revenue_gbp_30d"]
    paid = estimates["paid_subscription_30d"]
    integrity = experiment["integrity"]
    decision = experiment["decision"]
    processing = summary["processing_time"]

    if summary.get("version") != "0.32.0":
        _fail(f"generated summary version is {summary.get('version')}, not 0.32.0")

    quality = summary["quality"]
    for name in ("rows_raw", "rows_rejected", "rows_certified"):
        if int(_as_float(claims, name)) != int(quality[name]):
            _fail(f"{name} differs from generated quality evidence")

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
    _assert_close(claims, "pricing_experiment_paid_effect", 100.0 * paid["effect"], tol=1e-6)
    _assert_close(claims, "pricing_experiment_paid_ci_low", 100.0 * paid["ci_low"], tol=1e-6)
    _assert_close(claims, "pricing_experiment_paid_ci_high", 100.0 * paid["ci_high"], tol=1e-6)
    _assert_close(
        claims,
        "pricing_experiment_paid_harm_margin",
        100.0 * experiment["contract"]["paid_harm_guardrail"],
        tol=1e-12,
    )
    if claims.get("pricing_experiment_action") != decision["action"]:
        _fail("pricing_experiment_action differs from generated decision")

    point = processing["point_in_time_watermark_calibration"]
    stable = processing["watermark_stability_decision"]
    certified = processing["watermark_certification_decision"]
    plan = {float(row["allowed_lateness_hours"]): row for row in processing["watermark_evidence_plan"]}
    plan_decision = processing["watermark_evidence_plan_decision"]
    contract = processing["watermark_evidence_plan_contract"]

    _assert_close(claims, "point_in_time_selected_watermark", point["selected_lateness_hours"], tol=1e-12)
    _assert_close(claims, "stable_selected_watermark", stable["selected_lateness_hours"], tol=1e-12)
    if claims.get("certification_status") != certified["status"]:
        _fail("certification_status differs from generated decision")
    expected_certified = "none" if certified["selected_lateness_hours"] is None else str(certified["selected_lateness_hours"])
    if claims.get("certified_watermark") != expected_certified:
        _fail("certified_watermark differs from generated decision")
    _assert_close(claims, "evidence_plan_selected_watermark", plan_decision["selected_lateness_hours"], tol=1e-12)

    row48 = plan[48.0]
    row72 = plan[72.0]
    row96 = plan[96.0]
    numeric_pairs = {
        "evidence_plan_48h_required_late_trials": row48["required_late_event_trials"],
        "evidence_plan_48h_late_cycle": row48["late_event_audited_cycle_trials"],
        "evidence_plan_72h_required_revised_cells": row72["required_revised_metric_cells"],
        "evidence_plan_72h_revised_cycle": row72["revised_cell_audited_cycle_trials"],
        "evidence_plan_72h_revised_bound_days": row72["estimated_calendar_days_for_revision_bound"],
        "evidence_plan_96h_required_late_trials": row96["required_late_event_trials"],
        "evidence_plan_96h_late_cycle": row96["late_event_audited_cycle_trials"],
        "evidence_plan_96h_required_revised_cells": row96["required_revised_metric_cells"],
        "evidence_plan_96h_revised_cycle": row96["revised_cell_audited_cycle_trials"],
        "evidence_plan_96h_late_bound_days": row96["estimated_calendar_days_for_late_bound"],
        "evidence_plan_96h_revised_bound_days": row96["estimated_calendar_days_for_revision_bound"],
        "evidence_plan_96h_combined_days": row96["estimated_calendar_days_for_both_proportions"],
        "evidence_plan_96h_combined_years": row96["estimated_calendar_years_for_both_proportions"],
    }
    for name, expected in numeric_pairs.items():
        _assert_close(claims, name, expected, tol=1e-4 if name.endswith("years") else 1e-9)

    expected_global = str(bool(contract["global_monotonic_threshold_claimed"])).lower()
    if claims.get("global_monotonic_threshold_claimed") != expected_global:
        _fail("global_monotonic_threshold_claimed differs from generated contract")
    if int(_as_float(claims, "manifest_artifacts")) != int(manifest["artifact_count"]):
        _fail("manifest_artifacts differs from generated manifest")

    print(f"Static-claim validation passed: {ledger_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate checked-in public claims against generated reference evidence")
    parser.add_argument("root", nargs="?", default="build/reference")
    parser.add_argument("--ledger", default="results/reference_summary.csv")
    args = parser.parse_args()
    validate(Path(args.root), Path(args.ledger))


if __name__ == "__main__":
    main()
