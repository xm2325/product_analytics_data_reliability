from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd


REFERENCE_CANDIDATES = (24.0, 48.0, 72.0, 96.0)


def validate_reference_claims(root: Path) -> list[str]:
    """Validate deterministic v0.27 claims separately from generic invariants.

    `validate_build.py` checks that the selector is internally correct for any
    generated dataset. This companion gate pins the published seed=2206,
    days=120 reference result so a future code/data change cannot silently move
    the documented SLA while leaving README claims stale.
    """
    failures: list[str] = []
    grid_path = root / "watermark_policy_grid.csv"
    decision_path = root / "watermark_policy_decision.json"
    summary_path = root / "reference_summary.json"
    if not grid_path.is_file() or not decision_path.is_file() or not summary_path.is_file():
        return ["missing_v027_reference_evidence"]

    grid = pd.read_csv(grid_path).sort_values("allowed_lateness_hours").reset_index(drop=True)
    decision = json.loads(decision_path.read_text(encoding="utf-8"))
    summary = json.loads(summary_path.read_text(encoding="utf-8"))

    if tuple(grid["allowed_lateness_hours"].astype(float)) != REFERENCE_CANDIDATES:
        failures.append("reference_candidate_grid_changed")

    rows = {float(row["allowed_lateness_hours"]): row for _, row in grid.iterrows()}
    if 24.0 not in rows or 48.0 not in rows:
        failures.append("reference_24_or_48_missing")
        return failures

    row24 = rows[24.0]
    row48 = rows[48.0]
    feasible24 = str(row24["feasible"]).lower() == "true"
    feasible48 = str(row48["feasible"]).lower() == "true"
    if feasible24:
        failures.append("reference_24h_unexpectedly_feasible")
    if not feasible48:
        failures.append("reference_48h_unexpectedly_infeasible")
    if str(row24["passes_late_event_fraction"]).lower() != "false":
        failures.append("reference_24h_late_fraction_gate_no_longer_fails")
    if str(row24["passes_revised_metric_cell_fraction"]).lower() != "false":
        failures.append("reference_24h_revision_fraction_gate_no_longer_fails")

    if float(decision.get("selected_lateness_hours", -1)) != 48.0:
        failures.append("reference_selected_watermark_not_48h")
    if decision.get("weighted_score_used") is not False:
        failures.append("reference_selector_used_weighted_score")

    if summary.get("version") != "0.27.0":
        failures.append("reference_summary_version")
    calibration = summary.get("processing_time", {}).get("watermark_calibration", {})
    if float(calibration.get("selected_lateness_hours", -1)) != 48.0:
        failures.append("reference_summary_selected_watermark")

    return failures


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate pinned v0.27 deterministic reference claims")
    parser.add_argument("root", nargs="?", default="build/reference")
    args = parser.parse_args()
    failures = validate_reference_claims(Path(args.root))
    if failures:
        raise SystemExit("Reference-claim validation failed: " + ", ".join(failures))
    print(f"Reference-claim validation passed: {args.root}")


if __name__ == "__main__":
    main()
