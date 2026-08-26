from __future__ import annotations

import argparse
from dataclasses import asdict
from hashlib import sha256
import json
import math
from pathlib import Path

import pandas as pd

from product_analytics.evidence_invalidation import canonical_sha256
from product_analytics.forecasting import (
    evaluate_forecast_plan,
    mature_metric_history,
    rolling_origin_seasonal_naive,
)
from product_analytics.quality import certify_events_with_rejects


VERSION = "0.43.0"
SOURCE_PRODUCT = "notes_app"
INCIDENT_PRODUCT = "file_transfer"
EVENT_TYPE = "app_open"


def _read_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def _frame_sha256(frame: pd.DataFrame, *, sort_by: list[str]) -> str:
    ordered = frame.copy().sort_values(sort_by).reset_index(drop=True)
    for column in ordered.columns:
        if pd.api.types.is_datetime64_any_dtype(ordered[column]):
            ordered[column] = ordered[column].astype(str)
    payload = ordered.to_csv(index=False, lineterminator="\n", float_format="%.17g")
    return sha256(payload.encode("utf-8")).hexdigest()


def _daily_metrics(events: pd.DataFrame) -> pd.DataFrame:
    """Independent Pandas reconstruction of the controlled Gold contract."""
    df = events.copy()
    df["date"] = pd.to_datetime(df["event_ts"], utc=True, errors="raise").dt.date
    dau_legacy = df.groupby(["product", "date"])["user_id"].nunique().rename("dau_legacy_any_event")
    dau = (
        df.loc[df["event_type"].eq("app_open")]
        .groupby(["product", "date"])["user_id"]
        .nunique()
        .rename("dau")
    )
    counts = (
        df.loc[df["event_type"].isin(["first_open", "trial_start", "paid_subscription"])]
        .groupby(["product", "date", "event_type"])["user_id"]
        .nunique()
        .unstack("event_type", fill_value=0)
    )
    revenue = (
        df.loc[df["event_type"].eq("purchase")]
        .groupby(["product", "date"])["revenue_gbp"]
        .sum()
        .rename("revenue_gbp")
    )
    out = pd.concat([dau, dau_legacy, counts, revenue], axis=1).fillna(0).reset_index()
    for column in ["first_open", "trial_start", "paid_subscription"]:
        if column not in out:
            out[column] = 0
    out["dau"] = out["dau"].astype(int)
    out["dau_legacy_any_event"] = out["dau_legacy_any_event"].astype(int)
    out["dau_definition_delta"] = out["dau_legacy_any_event"] - out["dau"]
    out["dau_definition_delta_pct"] = out["dau_definition_delta"] / out["dau"].replace(0, pd.NA)
    out["conversion_first_open"] = out["paid_subscription"] / out["first_open"].replace(0, pd.NA)
    out["conversion_trial_start"] = out["paid_subscription"] / out["trial_start"].replace(0, pd.NA)
    return out.sort_values(["product", "date"]).reset_index(drop=True)


def _forecasts(gold: pd.DataFrame, silver: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for product in sorted(gold["product"].astype(str).unique()):
        history, cutoff = mature_metric_history(gold, silver, product)
        backtest = rolling_origin_seasonal_naive(history, "dau")
        row = asdict(evaluate_forecast_plan(f"{product}:dau", backtest))
        row["observation_cutoff"] = str(cutoff)
        rows.append(row)
    return pd.DataFrame(rows).sort_values("metric").reset_index(drop=True)


def _bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"true", "1"}:
        return True
    if text in {"false", "0"}:
        return False
    raise AssertionError(f"invalid boolean value {value!r}")


def _assert_forecasts(stored: pd.DataFrame, expected: pd.DataFrame, *, label: str) -> None:
    stored = stored.sort_values("metric").reset_index(drop=True)
    expected = expected.sort_values("metric").reset_index(drop=True)
    if list(stored.columns) != list(expected.columns) or len(stored) != len(expected):
        raise AssertionError(f"{label} forecast shape mismatch")
    bool_columns = {
        "approved",
        "enough_backtest_gate",
        "absolute_accuracy_gate",
        "benchmark_gate",
        "interval_coverage_gate",
    }
    for index in range(len(expected)):
        for column in expected.columns:
            left = stored.iloc[index][column]
            right = expected.iloc[index][column]
            if column in bool_columns:
                if _bool(left) != _bool(right):
                    raise AssertionError(f"{label} {index}/{column} mismatch")
            elif isinstance(right, (int, float)) and not isinstance(right, bool):
                if not math.isclose(float(left), float(right), rel_tol=0.0, abs_tol=1e-12):
                    raise AssertionError(f"{label} {index}/{column}: expected {right}, got {left}")
            elif str(left) != str(right):
                raise AssertionError(f"{label} {index}/{column}: expected {right}, got {left}")


def _changed_keys(left: pd.DataFrame, right: pd.DataFrame) -> set[tuple[str, object]]:
    left = left.sort_values(["product", "date"]).reset_index(drop=True)
    right = right.sort_values(["product", "date"]).reset_index(drop=True)
    if list(left[["product", "date"]].itertuples(index=False, name=None)) != list(
        right[["product", "date"]].itertuples(index=False, name=None)
    ):
        raise AssertionError("Gold key sets differ")
    changed = pd.Series(False, index=left.index)
    for column in [name for name in left.columns if name not in {"product", "date"}]:
        a = left[column]
        b = right[column]
        changed |= ~(a.eq(b) | (a.isna() & b.isna()))
    return set(zip(left.loc[changed, "product"].astype(str), left.loc[changed, "date"]))


def validate(base_dir: Path, output_dir: Path) -> None:
    evidence = _read_json(output_dir / "incident_recovery_evidence.json")
    lineage = _read_json(output_dir / "incident_lineage.json")
    if not isinstance(evidence, dict) or not isinstance(lineage, dict):
        raise AssertionError("v0.43 JSON evidence must be objects")
    if evidence.get("version") != VERSION or lineage.get("version") != VERSION:
        raise AssertionError("v0.43 evidence version mismatch")

    expected_policy = {
        "correction_key": "event_id",
        "partial_or_stale_correction_ledger_allowed": False,
        "affected_product_dates_must_be_explicit": True,
        "selective_replay_must_equal_clean_full_rebuild": True,
        "supersede_when_evidence_changes_even_if_action_does_not": True,
        "unaffected_forecast_decisions_must_be_reused_exactly": True,
        "performance_claim": "deterministic work counts only; no latency or speedup claim",
    }
    if evidence.get("policy") != expected_policy:
        raise AssertionError(f"unexpected v0.43 policy: {evidence.get('policy')}")

    clean_silver = pd.read_csv(base_dir / "silver_events.csv")
    clean_silver["event_ts"] = pd.to_datetime(clean_silver["event_ts"], utc=True, errors="raise")
    if "ingested_at" in clean_silver:
        clean_silver["ingested_at"] = pd.to_datetime(clean_silver["ingested_at"], utc=True, errors="raise")
    clean_gold = pd.read_csv(base_dir / "gold_daily_metrics.csv")
    clean_gold["date"] = pd.to_datetime(clean_gold["date"], errors="raise").dt.date
    clean_gold = clean_gold.sort_values(["product", "date"]).reset_index(drop=True)

    patch = pd.read_csv(output_dir / "incident_correction_ledger.csv", dtype={"event_id": str})
    if patch.empty or patch["event_id"].duplicated().any():
        raise AssertionError("correction ledger must be non-empty and unique by event_id")
    if set(patch["original_product"].astype(str)) != {SOURCE_PRODUCT}:
        raise AssertionError("unexpected original product in correction ledger")
    if set(patch["incident_product"].astype(str)) != {INCIDENT_PRODUCT}:
        raise AssertionError("unexpected incident product in correction ledger")
    if set(patch["event_type"].astype(str)) != {EVENT_TYPE}:
        raise AssertionError("correction ledger contains non-app_open rows")
    incident_dates = sorted(pd.to_datetime(patch["event_date"], errors="raise").dt.date.unique())
    if len(incident_dates) != 7 or incident_dates != pd.date_range(
        incident_dates[0], incident_dates[-1], freq="D"
    ).date.tolist():
        raise AssertionError("incident must cover exactly seven contiguous dates")

    ids = set(patch["event_id"].astype(str))
    base_ids = clean_silver["event_id"].astype(str)
    if not ids.issubset(set(base_ids)):
        raise AssertionError("correction ledger references events absent from clean Silver")
    base_patch_rows = clean_silver.loc[base_ids.isin(ids)].copy()
    if len(base_patch_rows) != len(patch):
        raise AssertionError("correction ledger does not map one-to-one to clean Silver")
    if set(base_patch_rows["product"].astype(str)) != {SOURCE_PRODUCT} or set(
        base_patch_rows["event_type"].astype(str)
    ) != {EVENT_TYPE}:
        raise AssertionError("correction ledger does not describe the declared clean source rows")

    incident_silver = clean_silver.copy()
    incident_silver.loc[base_ids.isin(ids), "product"] = INCIDENT_PRODUCT
    certified, quality, rejected = certify_events_with_rejects(incident_silver)
    if quality.rows_rejected != 0 or len(certified) != len(clean_silver) or not rejected.empty:
        raise AssertionError("schema-valid routing incident unexpectedly failed row-level quality")

    corrected_silver = incident_silver.copy()
    corrected_silver.loc[base_ids.isin(ids), "product"] = SOURCE_PRODUCT
    pd.testing.assert_frame_equal(corrected_silver, clean_silver, check_exact=True)

    incident_gold = _daily_metrics(incident_silver)
    corrected_full_gold = _daily_metrics(corrected_silver)
    # The frozen Gold CSV has crossed a decimal text serialization boundary.
    # Permit only round-trip floating-point noise here; targeted parity stays exact below.
    pd.testing.assert_frame_equal(
        corrected_full_gold,
        clean_gold,
        check_exact=False,
        rtol=0.0,
        atol=1e-12,
        check_dtype=False,
    )

    affected = pd.read_csv(output_dir / "incident_affected_product_dates.csv")
    affected["date"] = pd.to_datetime(affected["date"], errors="raise").dt.date
    expected_affected = {
        (product, day)
        for product in (SOURCE_PRODUCT, INCIDENT_PRODUCT)
        for day in incident_dates
    }
    actual_affected = set(zip(affected["product"].astype(str), affected["date"]))
    if actual_affected != expected_affected or len(affected) != 14:
        raise AssertionError("affected product-date lineage is not exactly 2 products x 7 days")

    changed = _changed_keys(incident_gold, corrected_full_gold)
    if changed != expected_affected:
        raise AssertionError("independent Gold change scope differs from declared lineage")

    stored_changed = pd.read_csv(output_dir / "incident_gold_change_evidence.csv")
    stored_changed["date"] = pd.to_datetime(stored_changed["date"], errors="raise").dt.date
    stored_changed_keys = set(zip(stored_changed["product"].astype(str), stored_changed["date"]))
    if stored_changed_keys != expected_affected or len(stored_changed) != 14:
        raise AssertionError("stored Gold change evidence scope mismatch")

    # Independently emulate targeted repair by replacing only the declared 14
    # product-date rows with rows from the corrected source aggregate.
    incident_keys = list(zip(incident_gold["product"].astype(str), incident_gold["date"]))
    untouched = incident_gold.loc[[key not in expected_affected for key in incident_keys]]
    corrected_keys = list(zip(corrected_full_gold["product"].astype(str), corrected_full_gold["date"]))
    replacements = corrected_full_gold.loc[[key in expected_affected for key in corrected_keys]]
    targeted_gold = pd.concat([untouched, replacements], ignore_index=True).sort_values(
        ["product", "date"]
    ).reset_index(drop=True)
    pd.testing.assert_frame_equal(targeted_gold, corrected_full_gold, check_exact=True)

    incident_forecasts = _forecasts(incident_gold, incident_silver)
    corrected_forecasts = _forecasts(corrected_full_gold, corrected_silver)
    _assert_forecasts(
        pd.read_csv(output_dir / "incident_forecast_evaluations.csv"),
        incident_forecasts,
        label="incident",
    )
    _assert_forecasts(
        pd.read_csv(output_dir / "corrected_forecast_evaluations.csv"),
        corrected_forecasts,
        label="corrected",
    )

    baseline = pd.read_csv(base_dir / "forecast_evaluations.csv")
    baseline_dau = baseline.loc[baseline["metric"].astype(str).str.endswith(":dau")].copy()
    baseline_dau = baseline_dau[corrected_forecasts.columns].sort_values("metric").reset_index(drop=True)
    _assert_forecasts(baseline_dau, corrected_forecasts, label="frozen baseline")

    for product in (SOURCE_PRODUCT, INCIDENT_PRODUCT):
        incident_row = incident_forecasts.loc[incident_forecasts["metric"].eq(f"{product}:dau")].iloc[0]
        corrected_row = corrected_forecasts.loc[corrected_forecasts["metric"].eq(f"{product}:dau")].iloc[0]
        if _bool(incident_row["approved"]):
            raise AssertionError(f"reference incident should withhold {product} planning evidence")
        if not _bool(corrected_row["approved"]):
            raise AssertionError(f"clean correction should restore {product} planning approval")
    photo_incident = incident_forecasts.loc[incident_forecasts["metric"].eq("photo_editor:dau")].iloc[0]
    photo_corrected = corrected_forecasts.loc[corrected_forecasts["metric"].eq("photo_editor:dau")].iloc[0]
    if canonical_sha256(photo_incident.to_dict()) != canonical_sha256(photo_corrected.to_dict()):
        raise AssertionError("unaffected photo_editor forecast evidence changed")

    decisions = pd.read_csv(output_dir / "decision_supersession_ledger.csv", dtype=str, keep_default_na=False)
    old_superseded = decisions.loc[decisions["status"].eq("SUPERSEDED")]
    new_active = decisions.loc[decisions["status"].eq("ACTIVE")]
    retained = decisions.loc[decisions["status"].eq("ACTIVE_UNCHANGED")]
    if len(old_superseded) != 2 or len(new_active) != 2 or len(retained) != 1:
        raise AssertionError("decision supersession cardinality mismatch")
    if set(old_superseded["metric"]) != {"file_transfer:dau", "notes_app:dau"}:
        raise AssertionError("wrong decisions were superseded")
    if set(retained["metric"]) != {"photo_editor:dau"}:
        raise AssertionError("unaffected decision was not retained")
    if not all(_bool(value) for value in old_superseded["action_changed"]):
        raise AssertionError("reference incident should change both affected actions")
    for row in old_superseded.to_dict(orient="records"):
        replacement = new_active.loc[new_active["decision_id"].eq(row["superseded_by"])]
        if len(replacement) != 1:
            raise AssertionError("superseded decision does not point to one active replacement")
        new = replacement.iloc[0]
        if str(new["supersedes"]) != str(row["decision_id"]):
            raise AssertionError("active replacement does not link back to superseded decision")
        if row["supersession_reason"] != "SOURCE_DATA_CORRECTION":
            raise AssertionError("unexpected supersession reason")

    summary = pd.read_csv(output_dir / "incident_recovery_summary.csv").iloc[0]
    expected_counts = {
        "incident_days": 7,
        "patched_events": len(patch),
        "row_level_quality_rejects": 0,
        "affected_products": 2,
        "affected_product_days": 14,
        "changed_gold_product_days": 14,
        "total_gold_rows": len(incident_gold),
        "selective_gold_rows_recomputed": 14,
        "gold_rows_not_recomputed": len(incident_gold) - 14,
        "forecast_series_recomputed": 2,
        "forecast_series_reused": 1,
        "superseded_decisions": 2,
        "action_changed_decisions": 2,
        "retained_decisions": 1,
    }
    for column, expected in expected_counts.items():
        if int(summary[column]) != int(expected):
            raise AssertionError(f"summary {column}: expected {expected}, got {summary[column]}")
    expected_reduction = 1.0 - 14 / len(incident_gold)
    if not math.isclose(float(summary["gold_recompute_reduction_fraction"]), expected_reduction, rel_tol=0, abs_tol=1e-12):
        raise AssertionError("deterministic Gold recompute reduction mismatch")
    for column in [
        "targeted_gold_equals_clean_rebuild",
        "targeted_forecasts_equal_clean_rebuild",
        "corrected_silver_equals_clean_source",
    ]:
        if not _bool(summary[column]):
            raise AssertionError(f"summary parity gate failed: {column}")

    hashes = evidence.get("hashes", {})
    expected_hashes = {
        "clean_silver_sha256": _frame_sha256(clean_silver, sort_by=["event_ts", "event_id"]),
        "incident_silver_sha256": _frame_sha256(incident_silver, sort_by=["event_ts", "event_id"]),
        "corrected_silver_sha256": _frame_sha256(corrected_silver, sort_by=["event_ts", "event_id"]),
        "incident_gold_sha256": _frame_sha256(incident_gold, sort_by=["product", "date"]),
        "targeted_corrected_gold_sha256": _frame_sha256(targeted_gold, sort_by=["product", "date"]),
        "clean_rebuild_gold_sha256": _frame_sha256(corrected_full_gold, sort_by=["product", "date"]),
        "incident_forecast_sha256": _frame_sha256(incident_forecasts, sort_by=["metric"]),
        "targeted_corrected_forecast_sha256": _frame_sha256(corrected_forecasts, sort_by=["metric"]),
        "clean_rebuild_forecast_sha256": _frame_sha256(corrected_forecasts, sort_by=["metric"]),
        "correction_ledger_sha256": _frame_sha256(patch, sort_by=["event_id"]),
    }
    if hashes != expected_hashes:
        raise AssertionError("independently recomputed v0.43 hashes differ from stored evidence")

    node_ids = {str(node["node_id"]) for node in lineage.get("nodes", [])}
    expected_nodes = {
        "source:routing:notes_app_app_open",
        "metric:file_transfer:dau",
        "metric:notes_app:dau",
        "forecast:file_transfer:dau",
        "forecast:notes_app:dau",
        "planning:file_transfer:dau",
        "planning:notes_app:dau",
    }
    if node_ids != expected_nodes or lineage.get("unaffected_decision") != "planning:photo_editor:dau":
        raise AssertionError("incident lineage graph changed")

    print(
        "Incident recovery validation passed: schema-valid 7-day routing incident; "
        f"{len(patch)} events corrected; 14/{len(incident_gold)} Gold rows rebuilt; "
        "2 forecasts replayed; 2 decisions superseded; targeted replay == clean rebuild"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Independently validate v0.43 incident recovery evidence")
    parser.add_argument("--base-dir", default="build/reference")
    parser.add_argument("--output-dir", default="build/incident-recovery")
    args = parser.parse_args()
    validate(Path(args.base_dir), Path(args.output_dir))


if __name__ == "__main__":
    main()
