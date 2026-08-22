from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import timedelta
from typing import Iterable

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class LateArrivalPolicy:
    allowed_lateness_hours: float = 48.0
    event_time_field: str = "event_ts"
    processing_time_field: str = "ingested_at"
    version: str = "1.0"


@dataclass(frozen=True)
class WatermarkRiskBudget:
    """Hard constraints for selecting the shortest acceptable watermark.

    The fields intentionally remain in their natural units. There is no
    weighted score that can trade a large revenue revision against a smaller
    late-event rate or vice versa.
    """

    max_late_event_fraction: float = 0.005
    max_revised_metric_cell_fraction: float = 0.01
    max_abs_revenue_revision_gbp: float = 10.0
    max_abs_paid_subscription_revision: float = 1.0
    version: str = "1.0"


DEFAULT_LATE_ARRIVAL_POLICY = LateArrivalPolicy()
DEFAULT_WATERMARK_RISK_BUDGET = WatermarkRiskBudget()
DEFAULT_WATERMARK_CANDIDATES = (24.0, 48.0, 72.0, 96.0)


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
    frame = _processing_frame(events)
    as_of = _utc_timestamp(processing_as_of)
    return frame.loc[frame["ingested_at"].le(as_of)].copy().reset_index(drop=True)


def watermark_event_date(
    processing_as_of: object,
    policy: LateArrivalPolicy = DEFAULT_LATE_ARRIVAL_POLICY,
):
    as_of = _utc_timestamp(processing_as_of)
    lateness = timedelta(seconds=int(round(policy.allowed_lateness_hours * 3600.0)))
    return (as_of - lateness).date()


def late_after_watermark_snapshot(
    events: pd.DataFrame,
    processing_as_of: object,
    policy: LateArrivalPolicy = DEFAULT_LATE_ARRIVAL_POLICY,
) -> pd.DataFrame:
    frame = with_lateness(events, policy)
    as_of = _utc_timestamp(processing_as_of)
    watermark_date = watermark_event_date(as_of, policy)
    event_date = frame["event_ts"].dt.date
    late = frame.loc[event_date.le(watermark_date) & frame["ingested_at"].gt(as_of)].copy()
    late["event_date"] = late["event_ts"].dt.date
    late["processing_as_of"] = as_of
    late["watermark_event_date"] = watermark_date
    columns = [
        "event_id", "user_id", "product", "event_type", "event_ts", "event_date",
        "ingested_at", "ingestion_delay_hours", "processing_as_of",
        "watermark_event_date", "revenue_gbp",
    ]
    return late[columns].sort_values(["event_date", "ingested_at", "event_id"]).reset_index(drop=True)


def metric_revision_report(
    events: pd.DataFrame,
    processing_as_of: object,
    policy: LateArrivalPolicy = DEFAULT_LATE_ARRIVAL_POLICY,
) -> pd.DataFrame:
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


def _metric_max_abs_revision(revisions: pd.DataFrame, metric: str) -> float:
    values = revisions.loc[revisions["metric"].eq(metric), "revision"]
    if values.empty:
        return 0.0
    return float(values.abs().max())


def watermark_policy_grid(
    events: pd.DataFrame,
    processing_as_of: object,
    candidate_hours: Iterable[float] = DEFAULT_WATERMARK_CANDIDATES,
    budget: WatermarkRiskBudget = DEFAULT_WATERMARK_RISK_BUDGET,
) -> pd.DataFrame:
    """Evaluate watermark latency versus exception/revision risk.

    Every candidate is replayed against the same certified event stream and
    processing-time snapshot. The table keeps each risk constraint separate so
    policy choice remains inspectable rather than hidden inside a score.
    """
    frame = _processing_frame(events)
    if frame.empty:
        raise ValueError("events must be non-empty")

    candidates = sorted({float(hours) for hours in candidate_hours})
    if not candidates or any(hours <= 0 for hours in candidates):
        raise ValueError("candidate_hours must contain positive values")

    rows: list[dict[str, object]] = []
    for hours in candidates:
        policy = LateArrivalPolicy(allowed_lateness_hours=hours)
        lateness = with_lateness(frame, policy)
        late_snapshot = late_after_watermark_snapshot(frame, processing_as_of, policy)
        revisions = metric_revision_report(frame, processing_as_of, policy)

        late_events = int(lateness["late_beyond_watermark"].sum())
        revised_cells = int(revisions["changed_after_watermark"].sum())
        finalized_metric_cells = int(len(revisions))
        finalized_calendar_dates = int(pd.Series(revisions["date"]).nunique()) if finalized_metric_cells else 0
        late_fraction = late_events / len(frame)
        revised_fraction = revised_cells / finalized_metric_cells if finalized_metric_cells else 0.0
        max_revenue = _metric_max_abs_revision(revisions, "revenue_gbp")
        max_paid = _metric_max_abs_revision(revisions, "paid_subscription")

        passes_late_fraction = late_fraction <= budget.max_late_event_fraction
        passes_revision_fraction = revised_fraction <= budget.max_revised_metric_cell_fraction
        passes_revenue_revision = max_revenue <= budget.max_abs_revenue_revision_gbp
        passes_paid_revision = max_paid <= budget.max_abs_paid_subscription_revision

        rows.append(
            {
                "allowed_lateness_hours": hours,
                "finalization_lag_days": hours / 24.0,
                "watermark_event_date": str(watermark_event_date(processing_as_of, policy)),
                "certified_events": int(len(frame)),
                "late_beyond_watermark_events": late_events,
                "late_event_fraction": float(late_fraction),
                "late_missing_from_finalized_snapshot": int(len(late_snapshot)),
                "finalized_calendar_dates": finalized_calendar_dates,
                "finalized_metric_cells": finalized_metric_cells,
                "revised_metric_cells": revised_cells,
                "revised_metric_cell_fraction": float(revised_fraction),
                "max_abs_dau_revision": _metric_max_abs_revision(revisions, "dau"),
                "max_abs_revenue_revision_gbp": max_revenue,
                "max_abs_paid_subscription_revision": max_paid,
                "passes_late_event_fraction": bool(passes_late_fraction),
                "passes_revised_metric_cell_fraction": bool(passes_revision_fraction),
                "passes_revenue_revision": bool(passes_revenue_revision),
                "passes_paid_subscription_revision": bool(passes_paid_revision),
                "feasible": bool(
                    passes_late_fraction
                    and passes_revision_fraction
                    and passes_revenue_revision
                    and passes_paid_revision
                ),
            }
        )
    return pd.DataFrame(rows).sort_values("allowed_lateness_hours").reset_index(drop=True)


def select_watermark_policy(
    policy_grid: pd.DataFrame,
    budget: WatermarkRiskBudget = DEFAULT_WATERMARK_RISK_BUDGET,
) -> dict[str, object]:
    """Select the shortest candidate that satisfies every hard constraint."""
    required = {
        "allowed_lateness_hours",
        "feasible",
        "late_event_fraction",
        "revised_metric_cell_fraction",
        "max_abs_revenue_revision_gbp",
        "max_abs_paid_subscription_revision",
    }
    missing = required.difference(policy_grid.columns)
    if missing:
        raise ValueError(f"policy_grid missing columns: {sorted(missing)}")

    feasible = policy_grid.loc[policy_grid["feasible"].astype(bool)].sort_values("allowed_lateness_hours")
    selected = None if feasible.empty else feasible.iloc[0]
    return {
        "version": "1.0",
        "selection_rule": "shortest candidate satisfying every hard risk constraint",
        "weighted_score_used": False,
        "budget": asdict(budget),
        "candidate_hours": [float(x) for x in sorted(policy_grid["allowed_lateness_hours"].unique())],
        "status": "selected" if selected is not None else "no_candidate_meets_budget",
        "selected_lateness_hours": None if selected is None else float(selected["allowed_lateness_hours"]),
        "selected_watermark_event_date": None if selected is None else str(selected.get("watermark_event_date", "")),
        "selected_evidence": None
        if selected is None
        else {
            "late_event_fraction": float(selected["late_event_fraction"]),
            "revised_metric_cell_fraction": float(selected["revised_metric_cell_fraction"]),
            "max_abs_revenue_revision_gbp": float(selected["max_abs_revenue_revision_gbp"]),
            "max_abs_paid_subscription_revision": float(selected["max_abs_paid_subscription_revision"]),
        },
    }


def late_arrival_contract(
    processing_as_of: object,
    policy: LateArrivalPolicy = DEFAULT_LATE_ARRIVAL_POLICY,
) -> dict[str, object]:
    return {
        **asdict(policy),
        "processing_as_of": str(_utc_timestamp(processing_as_of)),
        "watermark_event_date": str(watermark_event_date(processing_as_of, policy)),
        "finalization_rule": "event date <= watermark_event_date",
        "late_after_finalization_action": "reconcile and apply idempotent keyed backfill; never silently ignore",
        "metric_policy": "report provisional/final status separately from business value",
    }
