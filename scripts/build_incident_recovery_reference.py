from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path

import pandas as pd

from product_analytics.forecasting import (
    evaluate_forecast_plan,
    mature_metric_history,
    rolling_origin_seasonal_naive,
)
from product_analytics.incident_recovery import (
    ACTIVE,
    ACTIVE_UNCHANGED,
    SUPERSEDED,
    affected_product_dates,
    apply_product_routing_correction,
    build_decision_supersession_ledger,
    frame_sha256,
    inject_product_routing_incident,
    selective_recompute_gold,
)
from product_analytics.metrics import daily_metrics
from product_analytics.quality import certify_events_with_rejects


VERSION = "0.43.0"
SOURCE_PRODUCT = "notes_app"
INCIDENT_PRODUCT = "file_transfer"
INCIDENT_EVENT_TYPE = "app_open"
INCIDENT_ORIGIN_INDEX = 2


def _write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _normalise_gold(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    out["date"] = pd.to_datetime(out["date"], errors="raise").dt.date
    return out.sort_values(["product", "date"]).reset_index(drop=True)


def _assert_frozen_gold_equivalent(current: pd.DataFrame, frozen: pd.DataFrame) -> None:
    """Compare recomputed Gold with a CSV round-trip without weakening replay parity."""
    left = _normalise_gold(current)
    right = _normalise_gold(frozen)
    if list(left.columns) != list(right.columns) or len(left) != len(right):
        raise AssertionError("frozen Gold shape differs from clean recomputation")
    for column in ("product", "date"):
        if not left[column].equals(right[column]):
            raise AssertionError(f"frozen Gold key column differs: {column}")
    for column in [name for name in left.columns if name not in {"product", "date"}]:
        a = pd.to_numeric(left[column], errors="coerce")
        b = pd.to_numeric(right[column], errors="coerce")
        if not a.isna().equals(b.isna()):
            raise AssertionError(f"frozen Gold null pattern differs: {column}")
        present = a.notna()
        if ((a.loc[present] - b.loc[present]).abs() > 1e-12).any():
            raise AssertionError(f"frozen Gold values differ beyond CSV tolerance: {column}")


def _dau_forecasts(
    gold: pd.DataFrame,
    silver: pd.DataFrame,
    *,
    products: set[str] | None = None,
) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    product_values = sorted(gold["product"].astype(str).unique())
    if products is not None:
        product_values = [product for product in product_values if product in products]
    for product in product_values:
        history, cutoff = mature_metric_history(gold, silver, product)
        backtest = rolling_origin_seasonal_naive(history, "dau")
        evaluation = evaluate_forecast_plan(f"{product}:dau", backtest)
        row = asdict(evaluation)
        row["observation_cutoff"] = str(cutoff)
        rows.append(row)
    return pd.DataFrame(rows).sort_values("metric").reset_index(drop=True)


def _incident_window(clean_gold: pd.DataFrame, clean_silver: pd.DataFrame) -> tuple[object, object, list[str]]:
    history, _ = mature_metric_history(clean_gold, clean_silver, SOURCE_PRODUCT)
    horizon = 7
    origins = 4
    starts = list(range(len(history) - origins * horizon, len(history), horizon))
    start = starts[INCIDENT_ORIGIN_INDEX - 1]
    dates = pd.to_datetime(history.iloc[start : start + horizon]["date"], errors="raise").dt.date
    if len(dates) != horizon:
        raise AssertionError("incident window must contain exactly one seven-day forecast horizon")
    expected = pd.date_range(dates.iloc[0], dates.iloc[-1], freq="D").date.tolist()
    if dates.tolist() != expected:
        raise AssertionError("incident window is not seven contiguous calendar days")
    return dates.iloc[0], dates.iloc[-1], [str(value) for value in dates]


def _changed_gold_rows(incident_gold: pd.DataFrame, corrected_gold: pd.DataFrame) -> pd.DataFrame:
    left = _normalise_gold(incident_gold)
    right = _normalise_gold(corrected_gold)
    if list(left[["product", "date"]].itertuples(index=False, name=None)) != list(
        right[["product", "date"]].itertuples(index=False, name=None)
    ):
        raise AssertionError("incident and corrected Gold key sets differ")
    changed = pd.Series(False, index=left.index, dtype=bool)
    for column in [name for name in left.columns if name not in {"product", "date"}]:
        a = left[column]
        b = right[column]
        equal_values = a.eq(b).fillna(False)
        equal = equal_values | (a.isna() & b.isna())
        changed = changed | ~equal.astype(bool)
    keys = left.loc[changed, ["product", "date"]].copy()
    out = keys.copy()
    for column in ["dau", "dau_legacy_any_event"]:
        out[f"incident_{column}"] = left.loc[changed, column].to_numpy()
        out[f"corrected_{column}"] = right.loc[changed, column].to_numpy()
        out[f"delta_{column}"] = (
            right.loc[changed, column].to_numpy() - left.loc[changed, column].to_numpy()
        )
    return out.sort_values(["product", "date"]).reset_index(drop=True)


def _selective_forecast_replay(
    incident_forecasts: pd.DataFrame,
    corrected_gold: pd.DataFrame,
    corrected_silver: pd.DataFrame,
    affected_products: set[str],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    rebuilt = _dau_forecasts(corrected_gold, corrected_silver, products=affected_products)
    out = incident_forecasts.copy().set_index("metric", drop=False)
    for row in rebuilt.to_dict(orient="records"):
        metric = str(row["metric"])
        if metric not in out.index:
            raise AssertionError(f"rebuilt forecast metric is absent from incident evidence: {metric}")
        for column, value in row.items():
            out.loc[metric, column] = value
    out = out.reset_index(drop=True).sort_values("metric").reset_index(drop=True)
    return out, rebuilt


def build_reference(base_dir: Path, output_dir: Path) -> dict[str, object]:
    required = ["silver_events.csv", "gold_daily_metrics.csv", "forecast_evaluations.csv"]
    missing = [name for name in required if not (base_dir / name).is_file()]
    if missing:
        raise FileNotFoundError(f"Base controlled evidence is incomplete: {missing}")

    clean_silver = pd.read_csv(base_dir / "silver_events.csv")
    clean_silver["event_ts"] = pd.to_datetime(clean_silver["event_ts"], utc=True, errors="raise")
    if "ingested_at" in clean_silver:
        clean_silver["ingested_at"] = pd.to_datetime(
            clean_silver["ingested_at"], utc=True, errors="raise"
        )
    clean_gold = _normalise_gold(pd.read_csv(base_dir / "gold_daily_metrics.csv"))

    start_date, end_date, incident_dates = _incident_window(clean_gold, clean_silver)
    incident_silver, correction_ledger = inject_product_routing_incident(
        clean_silver,
        source_product=SOURCE_PRODUCT,
        incident_product=INCIDENT_PRODUCT,
        event_type=INCIDENT_EVENT_TYPE,
        start_date=start_date,
        end_date=end_date,
    )

    certified_incident, incident_quality, incident_rejected = certify_events_with_rejects(incident_silver)
    if incident_quality.rows_rejected != 0 or not incident_rejected.empty:
        raise AssertionError("routing incident should remain row-level contract-valid")
    if len(certified_incident) != len(incident_silver):
        raise AssertionError("routing incident changed the certified row count")

    incident_gold = _normalise_gold(daily_metrics(incident_silver))
    corrected_silver = apply_product_routing_correction(incident_silver, correction_ledger)
    pd.testing.assert_frame_equal(corrected_silver, clean_silver, check_exact=True)

    affected = affected_product_dates(correction_ledger)
    selective_gold, recomputed_gold = selective_recompute_gold(
        incident_gold,
        corrected_silver,
        affected,
    )
    selective_gold = _normalise_gold(selective_gold)
    clean_full_rebuild = _normalise_gold(daily_metrics(corrected_silver))
    pd.testing.assert_frame_equal(selective_gold, clean_full_rebuild, check_exact=True)
    _assert_frozen_gold_equivalent(clean_full_rebuild, clean_gold)

    changed_gold = _changed_gold_rows(incident_gold, clean_full_rebuild)
    affected_keys = set(zip(affected["product"].astype(str), affected["date"]))
    changed_keys = set(zip(changed_gold["product"].astype(str), changed_gold["date"]))
    if changed_keys != affected_keys:
        raise AssertionError(
            f"changed Gold scope differs from correction lineage: changed={sorted(changed_keys)}, affected={sorted(affected_keys)}"
        )

    incident_forecasts = _dau_forecasts(incident_gold, incident_silver)
    affected_products = set(affected["product"].astype(str))
    corrected_forecasts, rebuilt_forecasts = _selective_forecast_replay(
        incident_forecasts,
        selective_gold,
        corrected_silver,
        affected_products,
    )
    clean_full_forecasts = _dau_forecasts(clean_full_rebuild, corrected_silver)
    pd.testing.assert_frame_equal(corrected_forecasts, clean_full_forecasts, check_exact=True)

    baseline = pd.read_csv(base_dir / "forecast_evaluations.csv")
    baseline_dau = baseline.loc[baseline["metric"].astype(str).str.endswith(":dau")].copy()
    baseline_dau = baseline_dau[corrected_forecasts.columns].sort_values("metric").reset_index(drop=True)
    pd.testing.assert_frame_equal(
        corrected_forecasts,
        baseline_dau,
        check_exact=False,
        rtol=0.0,
        atol=1e-12,
        check_dtype=False,
    )

    unaffected_products = sorted(set(clean_gold["product"].astype(str)) - affected_products)
    for product in unaffected_products:
        metric = f"{product}:dau"
        before = incident_forecasts.loc[incident_forecasts["metric"].eq(metric)].reset_index(drop=True)
        after = corrected_forecasts.loc[corrected_forecasts["metric"].eq(metric)].reset_index(drop=True)
        pd.testing.assert_frame_equal(before, after, check_exact=True)

    decision_ledger = build_decision_supersession_ledger(incident_forecasts, corrected_forecasts)
    superseded = decision_ledger.loc[decision_ledger["status"].eq(SUPERSEDED)]
    active_replacements = decision_ledger.loc[decision_ledger["status"].eq(ACTIVE)]
    retained = decision_ledger.loc[decision_ledger["status"].eq(ACTIVE_UNCHANGED)]
    if len(superseded) != len(affected_products) or len(active_replacements) != len(affected_products):
        raise AssertionError("every affected forecast decision must be superseded exactly once")
    if len(retained) != len(unaffected_products):
        raise AssertionError("unaffected forecast decisions must be retained without replacement")

    action_changes = superseded.loc[superseded["action_changed"].astype(bool)]
    if len(action_changes) != len(affected_products):
        raise AssertionError("reference incident should reverse both affected planning actions")
    corrected_actions = {
        str(row["metric"]): ("PLAN" if bool(row["approved"]) else "WITHHOLD")
        for row in corrected_forecasts.to_dict(orient="records")
    }
    if corrected_actions.get("file_transfer:dau") != "PLAN" or corrected_actions.get("notes_app:dau") != "PLAN":
        raise AssertionError("clean controlled reference approvals changed unexpectedly")

    output_dir.mkdir(parents=True, exist_ok=True)
    correction_ledger.to_csv(output_dir / "incident_correction_ledger.csv", index=False)
    affected_out = affected.copy()
    affected_out["date"] = affected_out["date"].astype(str)
    affected_out.to_csv(output_dir / "incident_affected_product_dates.csv", index=False)
    changed_gold_out = changed_gold.copy()
    changed_gold_out["date"] = changed_gold_out["date"].astype(str)
    changed_gold_out.to_csv(output_dir / "incident_gold_change_evidence.csv", index=False)
    incident_forecasts.to_csv(output_dir / "incident_forecast_evaluations.csv", index=False)
    corrected_forecasts.to_csv(output_dir / "corrected_forecast_evaluations.csv", index=False)
    decision_ledger.to_csv(output_dir / "decision_supersession_ledger.csv", index=False)

    lineage = {
        "version": VERSION,
        "incident_root": "source:routing:notes_app_app_open",
        "nodes": [
            {
                "node_id": "source:routing:notes_app_app_open",
                "kind": "source_incident",
                "dependencies": [],
            },
            {
                "node_id": "metric:file_transfer:dau",
                "kind": "certified_metric",
                "dependencies": ["source:routing:notes_app_app_open"],
            },
            {
                "node_id": "metric:notes_app:dau",
                "kind": "certified_metric",
                "dependencies": ["source:routing:notes_app_app_open"],
            },
            {
                "node_id": "forecast:file_transfer:dau",
                "kind": "forecast_evidence",
                "dependencies": ["metric:file_transfer:dau"],
            },
            {
                "node_id": "forecast:notes_app:dau",
                "kind": "forecast_evidence",
                "dependencies": ["metric:notes_app:dau"],
            },
            {
                "node_id": "planning:file_transfer:dau",
                "kind": "planning_decision",
                "dependencies": ["forecast:file_transfer:dau"],
            },
            {
                "node_id": "planning:notes_app:dau",
                "kind": "planning_decision",
                "dependencies": ["forecast:notes_app:dau"],
            },
        ],
        "unaffected_decision": "planning:photo_editor:dau",
    }
    _write_json(output_dir / "incident_lineage.json", lineage)

    total_gold_rows = int(len(incident_gold))
    gold_rows_recomputed = int(len(recomputed_gold))
    summary = pd.DataFrame(
        [
            {
                "version": VERSION,
                "incident_type": "schema_valid_product_routing_error",
                "source_product": SOURCE_PRODUCT,
                "incident_product": INCIDENT_PRODUCT,
                "event_type": INCIDENT_EVENT_TYPE,
                "incident_start": str(start_date),
                "incident_end": str(end_date),
                "incident_days": len(incident_dates),
                "patched_events": len(correction_ledger),
                "row_level_quality_rejects": incident_quality.rows_rejected,
                "affected_products": len(affected_products),
                "affected_product_days": len(affected),
                "changed_gold_product_days": len(changed_gold),
                "total_gold_rows": total_gold_rows,
                "selective_gold_rows_recomputed": gold_rows_recomputed,
                "gold_rows_not_recomputed": total_gold_rows - gold_rows_recomputed,
                "gold_recompute_reduction_fraction": 1.0 - gold_rows_recomputed / total_gold_rows,
                "forecast_series_recomputed": len(rebuilt_forecasts),
                "forecast_series_reused": len(unaffected_products),
                "superseded_decisions": len(superseded),
                "action_changed_decisions": len(action_changes),
                "retained_decisions": len(retained),
                "targeted_gold_equals_clean_rebuild": True,
                "targeted_forecasts_equal_clean_rebuild": True,
                "corrected_silver_equals_clean_source": True,
            }
        ]
    )
    summary.to_csv(output_dir / "incident_recovery_summary.csv", index=False)

    evidence = {
        "version": VERSION,
        "base_reference_scope": "frozen controlled Gold/Silver and forecast evidence",
        "incident": {
            "type": "schema_valid_product_routing_error",
            "description": (
                "all notes_app app_open events in one historical seven-day forecast horizon were "
                "mislabelled as file_transfer while preserving valid event ids, event types, timestamps and revenue"
            ),
            "source_product": SOURCE_PRODUCT,
            "incident_product": INCIDENT_PRODUCT,
            "event_type": INCIDENT_EVENT_TYPE,
            "forecast_origin_index_contaminated": INCIDENT_ORIGIN_INDEX,
            "dates": incident_dates,
            "patched_events": int(len(correction_ledger)),
            "row_level_quality_rejects": int(incident_quality.rows_rejected),
        },
        "policy": {
            "correction_key": "event_id",
            "partial_or_stale_correction_ledger_allowed": False,
            "affected_product_dates_must_be_explicit": True,
            "selective_replay_must_equal_clean_full_rebuild": True,
            "supersede_when_evidence_changes_even_if_action_does_not": True,
            "unaffected_forecast_decisions_must_be_reused_exactly": True,
            "performance_claim": "deterministic work counts only; no latency or speedup claim",
        },
        "hashes": {
            "clean_silver_sha256": frame_sha256(clean_silver, sort_by=["event_ts", "event_id"]),
            "incident_silver_sha256": frame_sha256(incident_silver, sort_by=["event_ts", "event_id"]),
            "corrected_silver_sha256": frame_sha256(corrected_silver, sort_by=["event_ts", "event_id"]),
            "incident_gold_sha256": frame_sha256(incident_gold, sort_by=["product", "date"]),
            "targeted_corrected_gold_sha256": frame_sha256(selective_gold, sort_by=["product", "date"]),
            "clean_rebuild_gold_sha256": frame_sha256(clean_full_rebuild, sort_by=["product", "date"]),
            "incident_forecast_sha256": frame_sha256(incident_forecasts, sort_by=["metric"]),
            "targeted_corrected_forecast_sha256": frame_sha256(corrected_forecasts, sort_by=["metric"]),
            "clean_rebuild_forecast_sha256": frame_sha256(clean_full_forecasts, sort_by=["metric"]),
            "correction_ledger_sha256": frame_sha256(correction_ledger, sort_by=["event_id"]),
        },
        "work": {
            "total_gold_rows": total_gold_rows,
            "gold_rows_recomputed": gold_rows_recomputed,
            "gold_rows_reused": total_gold_rows - gold_rows_recomputed,
            "forecast_series_recomputed": int(len(rebuilt_forecasts)),
            "forecast_series_reused": int(len(unaffected_products)),
            "planning_decisions_superseded": int(len(superseded)),
            "planning_decisions_retained": int(len(retained)),
        },
        "decision_actions": {
            str(row["metric"]): {
                "incident_action": str(
                    decision_ledger.loc[
                        decision_ledger["decision_id"].eq(f"{row['metric']}|incident"), "action"
                    ].iloc[0]
                ),
                "corrected_action": corrected_actions[str(row["metric"])],
            }
            for row in corrected_forecasts.to_dict(orient="records")
        },
    }
    if evidence["hashes"]["clean_silver_sha256"] != evidence["hashes"]["corrected_silver_sha256"]:
        raise AssertionError("corrected Silver hash does not restore clean source")
    if evidence["hashes"]["targeted_corrected_gold_sha256"] != evidence["hashes"]["clean_rebuild_gold_sha256"]:
        raise AssertionError("targeted Gold hash differs from clean rebuild")
    if evidence["hashes"]["targeted_corrected_forecast_sha256"] != evidence["hashes"]["clean_rebuild_forecast_sha256"]:
        raise AssertionError("targeted forecast hash differs from clean rebuild")
    _write_json(output_dir / "incident_recovery_evidence.json", evidence)

    return {
        "version": VERSION,
        "incident_dates": incident_dates,
        "patched_events": int(len(correction_ledger)),
        "affected_product_days": int(len(affected)),
        "gold_rows_recomputed": gold_rows_recomputed,
        "gold_rows_total": total_gold_rows,
        "forecast_series_recomputed": int(len(rebuilt_forecasts)),
        "superseded_decisions": int(len(superseded)),
        "action_changed_decisions": int(len(action_changes)),
        "retained_decisions": int(len(retained)),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Build v0.43 incident correction and selective replay evidence")
    parser.add_argument("--base-dir", default="build/reference")
    parser.add_argument("--output-dir", default="build/incident-recovery")
    args = parser.parse_args()
    result = build_reference(Path(args.base_dir), Path(args.output_dir))
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
