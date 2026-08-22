from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class LateArrivalPolicy:
    allowed_lateness_hours: float = 48.0
    event_time_field: str = "event_ts"
    processing_time_field: str = "ingested_at"
    version: str = "1.0"


DEFAULT_LATE_ARRIVAL_POLICY = LateArrivalPolicy()


def _utc_timestamp(value: object) -> pd.Timestamp:
    ts = pd.Timestamp(value)
    if ts.tzinfo is None:
        return ts.tz_localize("UTC")
    return ts.tz_convert("UTC")


def _processing_frame(events: pd.DataFrame) -> pd.DataFrame:
    if "event_ts" not in events:
        raise ValueError("events must contain event_ts")
    frame = events.copy()
    frame["event_ts"] = pd.to_datetime(frame["event_ts"], utc=True, errors="raise")
    if "ingested_at" not in frame:
        frame["ingested_at"] = frame["event_ts"]
    frame["ingested_at"] = pd.to_datetime(frame["ingested_at"], utc=True, errors="raise")
    if frame["ingested_at"].lt(frame["event_ts"]).any():
        raise ValueError("ingested_at must be on or after event_ts")
    return frame


def with_lateness(
    events: pd.DataFrame,
    policy: LateArrivalPolicy = DEFAULT_LATE_ARRIVAL_POLICY,
) -> pd.DataFrame:
    """Attach processing-delay and watermark-breach fields to certified events."""
    frame = _processing_frame(events)
    frame["ingestion_delay_hours"] = (
        frame["ingested_at"] - frame["event_ts"]
    ).dt.total_seconds() / 3600.0
    frame["late_beyond_watermark"] = frame["ingestion_delay_hours"].gt(policy.allowed_lateness_hours)
    return frame


def late_arrival_summary(
    events: pd.DataFrame,
    policy: LateArrivalPolicy = DEFAULT_LATE_ARRIVAL_POLICY,
) -> pd.DataFrame:
    """Summarise processing latency without mixing it into business KPIs."""
    frame = with_lateness(events, policy)
    out = (
        frame.groupby(["product", "event_type"], as_index=False)
        .agg(
            events=("event_id", "size"),
            late_beyond_watermark=("late_beyond_watermark", "sum"),
            delay_p50_hours=("ingestion_delay_hours", "median"),
            delay_p95_hours=("ingestion_delay_hours", lambda values: float(values.quantile(0.95))),
            delay_max_hours=("ingestion_delay_hours", "max"),
        )
    )
    out["late_fraction"] = out["late_beyond_watermark"] / out["events"]
    return out.sort_values(["product", "event_type"]).reset_index(drop=True)


def available_as_of(events: pd.DataFrame, processing_as_of: object) -> pd.DataFrame:
    """Return only rows that had reached the platform by a processing-time snapshot."""
    frame = _processing_frame(events)
    as_of = _utc_timestamp(processing_as_of)
    return frame.loc[frame["ingested_at"].le(as_of)].copy().reset_index(drop=True)


def watermark_event_date(
    processing_as_of: object,
    policy: LateArrivalPolicy = DEFAULT_LATE_ARRIVAL_POLICY,
):
    """Latest event date nominally final under a processing-time watermark."""
    as_of = _utc_timestamp(processing_as_of)
    return (as_of - pd.Timedelta(hours=policy.allowed_lateness_hours)).date()


def late_after_watermark_snapshot(
    events: pd.DataFrame,
    processing_as_of: object,
    policy: LateArrivalPolicy = DEFAULT_LATE_ARRIVAL_POLICY,
) -> pd.DataFrame:
    """Events missing at snapshot time for event dates the watermark called final."""
    frame = with_lateness(events, policy)
    as_of = _utc_timestamp(processing_as_of)
    watermark_date = watermark_event_date(as_of, policy)
    event_date = frame["event_ts"].dt.date
    late = frame.loc[event_date.le(watermark_date) & frame["ingested_at"].gt(as_of)].copy()
    late["event_date"] = late["event_ts"].dt.date
    late["processing_as_of"] = as_of
    late["watermark_event_date"] = watermark_date
    columns = [
        "event_id",
        "user_id",
        "product",
        "event_type",
        "event_ts",
        "event_date",
        "ingested_at",
        "ingestion_delay_hours",
        "processing_as_of",
        "watermark_event_date",
        "revenue_gbp",
    ]
    return late[columns].sort_values(["event_date", "ingested_at", "event_id"]).reset_index(drop=True)


def metric_revision_report(
    events: pd.DataFrame,
    processing_as_of: object,
    policy: LateArrivalPolicy = DEFAULT_LATE_ARRIVAL_POLICY,
) -> pd.DataFrame:
    """Compare as-of versus settled KPIs for dates nominally behind watermark.

    The settled view uses all currently supplied certified rows, while the
    snapshot view uses only rows ingested by ``processing_as_of``. Restricting
    comparison to event dates at or before the watermark isolates corrections
    to dates that the operating policy would otherwise have called final.
    """
    from .metrics import daily_metrics

    settled_events = _processing_frame(events)
    snapshot_events = available_as_of(settled_events, processing_as_of)
    watermark_date = watermark_event_date(processing_as_of, policy)

    def long_metrics(frame: pd.DataFrame, value_name: str) -> pd.DataFrame:
        gold = daily_metrics(frame)
        gold = gold.loc[pd.to_datetime(gold["date"]).dt.date.le(watermark_date)].copy()
        parts = []
        for metric in ["dau", "revenue_gbp", "paid_subscription"]:
            part = gold[["product", "date", metric]].rename(columns={metric: value_name})
            part["metric"] = metric
            parts.append(part)
        if not parts:
            return pd.DataFrame(columns=["product", "date", value_name, "metric"])
        return pd.concat(parts, ignore_index=True)

    snapshot = long_metrics(snapshot_events, "snapshot_value")
    settled = long_metrics(settled_events, "settled_value")
    out = snapshot.merge(settled, on=["product", "date", "metric"], how="outer").fillna(
        {"snapshot_value": 0.0, "settled_value": 0.0}
    )
    out["revision"] = out["settled_value"] - out["snapshot_value"]
    denominator = out["snapshot_value"].abs().replace(0, np.nan)
    out["revision_pct"] = out["revision"] / denominator
    out["changed_after_watermark"] = out["revision"].abs().gt(1e-12)
    out["processing_as_of"] = _utc_timestamp(processing_as_of)
    out["watermark_event_date"] = watermark_date
    return out.sort_values(["product", "date", "metric"]).reset_index(drop=True)


def revision_summary(revisions: pd.DataFrame) -> pd.DataFrame:
    """Aggregate watermark revisions without hiding the affected metric."""
    out = (
        revisions.groupby(["product", "metric"], as_index=False)
        .agg(
            finalized_dates=("date", "size"),
            revised_dates=("changed_after_watermark", "sum"),
            total_revision=("revision", "sum"),
            max_abs_revision=("revision", lambda values: float(values.abs().max())),
        )
    )
    out["revised_date_fraction"] = out["revised_dates"] / out["finalized_dates"]
    return out.sort_values(["product", "metric"]).reset_index(drop=True)


def late_arrival_contract(
    processing_as_of: object,
    policy: LateArrivalPolicy = DEFAULT_LATE_ARRIVAL_POLICY,
) -> dict[str, object]:
    """Machine-readable processing-time policy for generated evidence."""
    return {
        **asdict(policy),
        "processing_as_of": str(_utc_timestamp(processing_as_of)),
        "watermark_event_date": str(watermark_event_date(processing_as_of, policy)),
        "finalization_rule": "event date <= watermark_event_date",
        "late_after_finalization_action": "reconcile and apply idempotent keyed backfill; never silently ignore",
        "metric_policy": "report provisional/final status separately from business value",
    }
