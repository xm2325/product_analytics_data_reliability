from __future__ import annotations

from hashlib import sha256
from typing import Iterable

import pandas as pd

from .evidence_invalidation import canonical_sha256
from .metrics import daily_metrics


SUPERSEDED = "SUPERSEDED"
ACTIVE = "ACTIVE"
ACTIVE_UNCHANGED = "ACTIVE_UNCHANGED"
SOURCE_DATA_CORRECTION = "SOURCE_DATA_CORRECTION"
_RATIO_COLUMNS = {
    "dau_definition_delta_pct",
    "conversion_first_open",
    "conversion_trial_start",
}


def _required(frame: pd.DataFrame, columns: Iterable[str], *, label: str) -> None:
    missing = set(columns) - set(frame.columns)
    if missing:
        raise ValueError(f"{label} missing columns: {sorted(missing)}")


def frame_sha256(frame: pd.DataFrame, *, sort_by: Iterable[str]) -> str:
    ordered = frame.copy().sort_values(list(sort_by)).reset_index(drop=True)
    for column in ordered.columns:
        if pd.api.types.is_datetime64_any_dtype(ordered[column]):
            ordered[column] = ordered[column].astype(str)
    payload = ordered.to_csv(index=False, lineterminator="\n", float_format="%.17g")
    return sha256(payload.encode("utf-8")).hexdigest()


def inject_product_routing_incident(
    certified_events: pd.DataFrame,
    *,
    source_product: str,
    incident_product: str,
    event_type: str,
    start_date: object,
    end_date: object,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Inject a schema-valid product-routing error and return its correction ledger."""
    _required(certified_events, ("event_id", "product", "event_type", "event_ts"), label="certified events")
    if source_product == incident_product:
        raise ValueError("source_product and incident_product must differ")
    if certified_events["event_id"].duplicated().any():
        raise ValueError("certified events must have unique event_id values")

    start = pd.Timestamp(start_date).date()
    end = pd.Timestamp(end_date).date()
    if end < start:
        raise ValueError("end_date must be on or after start_date")

    out = certified_events.copy()
    event_date = pd.to_datetime(out["event_ts"], utc=True, errors="raise").dt.date
    mask = (
        out["product"].eq(source_product)
        & out["event_type"].eq(event_type)
        & event_date.ge(start)
        & event_date.le(end)
    )
    if not mask.any():
        raise ValueError("incident selector matched no certified events")

    patch = out.loc[mask, ["event_id", "event_ts", "event_type"]].copy()
    patch["event_date"] = event_date.loc[mask].astype(str).to_numpy()
    patch["original_product"] = source_product
    patch["incident_product"] = incident_product
    patch = patch[[
        "event_id", "event_ts", "event_date", "event_type",
        "original_product", "incident_product",
    ]].sort_values("event_id").reset_index(drop=True)
    if patch["event_id"].duplicated().any():
        raise AssertionError("incident patch ledger contains duplicate event ids")

    out.loc[mask, "product"] = incident_product
    return out, patch


def apply_product_routing_correction(
    incident_events: pd.DataFrame,
    correction_ledger: pd.DataFrame,
) -> pd.DataFrame:
    """Restore product labels by event_id and reject stale/tampered corrections."""
    _required(incident_events, ("event_id", "product", "event_type", "event_ts"), label="incident events")
    _required(
        correction_ledger,
        ("event_id", "event_type", "event_date", "original_product", "incident_product"),
        label="correction ledger",
    )
    if incident_events["event_id"].duplicated().any():
        raise ValueError("incident events must have unique event_id values")
    if correction_ledger["event_id"].duplicated().any():
        raise ValueError("correction ledger must have unique event_id values")

    ids = set(correction_ledger["event_id"].astype(str))
    observed_ids = set(incident_events["event_id"].astype(str))
    unknown = sorted(ids - observed_ids)
    if unknown:
        raise ValueError(f"correction ledger contains unknown event ids: {unknown[:5]}")

    out = incident_events.copy()
    patch = correction_ledger.copy()
    patch["event_id"] = patch["event_id"].astype(str)
    lookup = out[["event_id", "product", "event_type", "event_ts"]].copy()
    lookup["event_id"] = lookup["event_id"].astype(str)
    joined = patch.merge(lookup, on="event_id", how="left", validate="one_to_one", suffixes=("_patch", "_observed"))

    bad_product = ~joined["product"].astype(str).eq(joined["incident_product"].astype(str))
    bad_type = ~joined["event_type_observed"].astype(str).eq(joined["event_type_patch"].astype(str))
    observed_date = pd.to_datetime(joined["event_ts_observed"], utc=True, errors="raise").dt.date.astype(str)
    bad_date = ~observed_date.eq(joined["event_date"].astype(str))
    if bad_product.any() or bad_type.any() or bad_date.any():
        raise ValueError("correction ledger no longer matches the incident event state")

    restore = patch.set_index("event_id")["original_product"].astype(str).to_dict()
    event_ids = out["event_id"].astype(str)
    affected = event_ids.isin(ids)
    out.loc[affected, "product"] = event_ids.loc[affected].map(restore).to_numpy()
    return out


def affected_product_dates(correction_ledger: pd.DataFrame) -> pd.DataFrame:
    _required(correction_ledger, ("event_date", "original_product", "incident_product"), label="correction ledger")
    source = correction_ledger[["event_date", "original_product"]].rename(
        columns={"event_date": "date", "original_product": "product"}
    )
    target = correction_ledger[["event_date", "incident_product"]].rename(
        columns={"event_date": "date", "incident_product": "product"}
    )
    out = pd.concat([source, target], ignore_index=True).drop_duplicates()
    out["date"] = pd.to_datetime(out["date"], errors="raise").dt.date
    return out.sort_values(["product", "date"]).reset_index(drop=True)


def _normalise_gold_dtypes(frame: pd.DataFrame, template: pd.DataFrame) -> pd.DataFrame:
    """Mirror the existing daily_metrics dtype behaviour after partial stitching."""
    out = frame.copy()
    for column in template.columns:
        if column in _RATIO_COLUMNS:
            numeric = pd.to_numeric(out[column], errors="coerce")
            if numeric.isna().any():
                values = numeric.astype(object)
                values.loc[numeric.isna()] = pd.NA
                out[column] = values
            else:
                out[column] = numeric.astype(float)
            continue
        target_dtype = template[column].dtype
        if pd.api.types.is_numeric_dtype(target_dtype):
            out[column] = pd.to_numeric(out[column], errors="coerce").astype(target_dtype)
        elif column != "date" and str(target_dtype) != "object":
            out[column] = out[column].astype(target_dtype)
    return out


def selective_recompute_gold(
    incident_gold: pd.DataFrame,
    corrected_events: pd.DataFrame,
    affected_dates: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Recompute only affected product-date Gold rows after a source correction."""
    _required(incident_gold, ("product", "date"), label="incident Gold")
    _required(corrected_events, ("product", "event_ts"), label="corrected events")
    _required(affected_dates, ("product", "date"), label="affected dates")

    gold = incident_gold.copy()
    gold["date"] = pd.to_datetime(gold["date"], errors="raise").dt.date
    if gold.duplicated(["product", "date"]).any():
        raise ValueError("incident Gold must be unique by product/date")

    affected = affected_dates.copy()
    affected["date"] = pd.to_datetime(affected["date"], errors="raise").dt.date
    keys = set(zip(affected["product"].astype(str), affected["date"]))
    if not keys:
        raise ValueError("affected product-date set is empty")

    events = corrected_events.copy()
    events["_event_date"] = pd.to_datetime(events["event_ts"], utc=True, errors="raise").dt.date
    event_keys = list(zip(events["product"].astype(str), events["_event_date"]))
    subset = events.loc[[key in keys for key in event_keys]].drop(columns=["_event_date"])
    if subset.empty:
        raise ValueError("no corrected events found for affected product-dates")

    recomputed = daily_metrics(subset)
    recomputed["date"] = pd.to_datetime(recomputed["date"], errors="raise").dt.date
    recomputed_keys = set(zip(recomputed["product"].astype(str), recomputed["date"]))
    if recomputed_keys != keys:
        missing = sorted(keys - recomputed_keys)
        extra = sorted(recomputed_keys - keys)
        raise ValueError(f"selective Gold key mismatch; missing={missing}, extra={extra}")

    gold_keys = list(zip(gold["product"].astype(str), gold["date"]))
    untouched = gold.loc[[key not in keys for key in gold_keys]]
    result = pd.concat([untouched, recomputed[gold.columns]], ignore_index=True)
    result = _normalise_gold_dtypes(result, gold)
    result = result.sort_values(["product", "date"]).reset_index(drop=True)
    if len(result) != len(gold) or result.duplicated(["product", "date"]).any():
        raise AssertionError("selective Gold replay changed the product-date key set")

    recomputed_out = result.loc[
        [key in keys for key in zip(result["product"].astype(str), result["date"])]
    ].reset_index(drop=True)
    return result, recomputed_out


def _as_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"true", "1"}:
        return True
    if text in {"false", "0"}:
        return False
    raise ValueError(f"cannot interpret boolean value {value!r}")


def build_decision_supersession_ledger(
    incident_forecasts: pd.DataFrame,
    corrected_forecasts: pd.DataFrame,
) -> pd.DataFrame:
    """Supersede a published decision whenever its forecast evidence changes."""
    _required(incident_forecasts, ("metric", "approved"), label="incident forecasts")
    _required(corrected_forecasts, ("metric", "approved"), label="corrected forecasts")
    incident = incident_forecasts.sort_values("metric").reset_index(drop=True)
    corrected = corrected_forecasts.sort_values("metric").reset_index(drop=True)
    if list(incident["metric"].astype(str)) != list(corrected["metric"].astype(str)):
        raise ValueError("incident/corrected forecast metric sets differ")

    rows: list[dict[str, object]] = []
    for incident_row, corrected_row in zip(incident.to_dict(orient="records"), corrected.to_dict(orient="records")):
        metric = str(incident_row["metric"])
        incident_fp = canonical_sha256(incident_row)
        corrected_fp = canonical_sha256(corrected_row)
        incident_action = "PLAN" if _as_bool(incident_row["approved"]) else "WITHHOLD"
        corrected_action = "PLAN" if _as_bool(corrected_row["approved"]) else "WITHHOLD"
        evidence_changed = incident_fp != corrected_fp
        action_changed = incident_action != corrected_action
        old_id = f"{metric}|incident"

        if not evidence_changed:
            rows.append({
                "decision_id": old_id,
                "metric": metric,
                "evidence_state": "incident_published",
                "action": incident_action,
                "evidence_sha256": incident_fp,
                "status": ACTIVE_UNCHANGED,
                "superseded_by": "",
                "supersedes": "",
                "supersession_reason": "",
                "evidence_changed": False,
                "action_changed": False,
            })
            continue

        new_id = f"{metric}|corrected"
        rows.append({
            "decision_id": old_id,
            "metric": metric,
            "evidence_state": "incident_published",
            "action": incident_action,
            "evidence_sha256": incident_fp,
            "status": SUPERSEDED,
            "superseded_by": new_id,
            "supersedes": "",
            "supersession_reason": SOURCE_DATA_CORRECTION,
            "evidence_changed": True,
            "action_changed": action_changed,
        })
        rows.append({
            "decision_id": new_id,
            "metric": metric,
            "evidence_state": "corrected_replay",
            "action": corrected_action,
            "evidence_sha256": corrected_fp,
            "status": ACTIVE,
            "superseded_by": "",
            "supersedes": old_id,
            "supersession_reason": SOURCE_DATA_CORRECTION,
            "evidence_changed": True,
            "action_changed": action_changed,
        })
    return pd.DataFrame(rows)
