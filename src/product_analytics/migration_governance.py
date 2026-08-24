from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass
from typing import Any

import pandas as pd

from .contracts import event_contract


MIGRATION_TOLERANCE = 0.01


@dataclass(frozen=True)
class ContractClassification:
    classification: str
    producer_compatible: bool
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class MigrationDecision:
    proposal: str
    classification: str
    producer_compatible_gate: bool
    metric_invariance_gate: bool
    forecast_eligibility_gate: bool
    approved: bool
    action: str
    reason: str


def migration_proposals() -> dict[str, dict[str, Any]]:
    """Return deterministic controlled proposals used by the reference migration study."""
    current = event_contract()

    additive = deepcopy(current)
    additive["version"] = "1.3"
    additive["optional_dimensions"] = sorted(set(additive["optional_dimensions"]) | {"country"})

    breaking = deepcopy(current)
    breaking["version"] = "2.0-breaking"
    breaking["required_columns"] = [
        "event_uuid" if column == "event_id" else column for column in breaking["required_columns"]
    ]
    breaking["rules"] = dict(breaking["rules"])
    breaking["rules"].pop("event_id", None)
    breaking["rules"]["event_uuid"] = "non-null event identifier; duplicate identifiers are rejected after the first row"

    semantic = deepcopy(current)
    semantic["version"] = "1.3-semantic-candidate"
    semantic["activity_event"] = "any_certified_event"
    semantic["rules"] = dict(semantic["rules"])
    semantic["rules"]["active_use"] = "daily active use is identified by any certified event"

    return {
        "add_optional_country": additive,
        "rename_required_event_id": breaking,
        "broaden_dau_to_any_event": semantic,
    }


def classify_event_contract_change(
    current: dict[str, Any], proposed: dict[str, Any]
) -> ContractClassification:
    """Classify a proposed event-contract change without trusting a version label."""
    reasons: list[str] = []

    current_required = set(current.get("required_columns", []))
    proposed_required = set(proposed.get("required_columns", []))
    if current_required != proposed_required:
        removed = sorted(current_required - proposed_required)
        added = sorted(proposed_required - current_required)
        if removed:
            reasons.append(f"required columns removed or renamed: {removed}")
        if added:
            reasons.append(f"new required columns break old producers: {added}")
        return ContractClassification("BREAKING", False, tuple(reasons))

    for key in ("grain", "generated_processing_time_column"):
        if current.get(key) != proposed.get(key):
            reasons.append(f"{key} changed")
            return ContractClassification("BREAKING", False, tuple(reasons))

    current_products = set(current.get("allowed_products", []))
    proposed_products = set(proposed.get("allowed_products", []))
    current_events = set(current.get("allowed_event_types", []))
    proposed_events = set(proposed.get("allowed_event_types", []))
    if not current_products.issubset(proposed_products):
        reasons.append("allowed products were removed")
        return ContractClassification("BREAKING", False, tuple(reasons))
    if not current_events.issubset(proposed_events):
        reasons.append("allowed event types were removed")
        return ContractClassification("BREAKING", False, tuple(reasons))

    if current.get("activity_event") != proposed.get("activity_event"):
        reasons.append("activity metric semantics changed")
    if current.get("rules") != proposed.get("rules"):
        reasons.append("validation or metric rules changed")
    if current.get("legacy_processing_time_fallback") != proposed.get("legacy_processing_time_fallback"):
        reasons.append("processing-time fallback semantics changed")
    if reasons:
        return ContractClassification("SEMANTIC", True, tuple(reasons))

    current_optional = set(current.get("optional_dimensions", []))
    proposed_optional = set(proposed.get("optional_dimensions", []))
    if not current_optional.issubset(proposed_optional):
        reasons.append("optional dimensions were removed")
        return ContractClassification("BREAKING", False, tuple(reasons))
    if proposed_optional != current_optional:
        reasons.append(f"optional dimensions added: {sorted(proposed_optional - current_optional)}")
    if proposed_products != current_products:
        reasons.append(f"allowed products added: {sorted(proposed_products - current_products)}")
    if proposed_events != current_events:
        reasons.append(f"allowed event types added: {sorted(proposed_events - current_events)}")
    if reasons:
        return ContractClassification("ADDITIVE", True, tuple(reasons))

    return ContractClassification("NO_CHANGE", True, ("contract is identical",))


def dau_shadow_replay(gold_metrics: pd.DataFrame) -> pd.DataFrame:
    """Replay current DAU v2 against the deprecated any-event candidate on identical evidence."""
    required = {
        "product",
        "date",
        "dau",
        "dau_legacy_any_event",
        "paid_subscription",
        "revenue_gbp",
    }
    missing = required.difference(gold_metrics.columns)
    if missing:
        raise ValueError(f"Missing Gold columns for migration replay: {sorted(missing)}")

    out = gold_metrics[
        ["product", "date", "dau", "dau_legacy_any_event", "paid_subscription", "revenue_gbp"]
    ].copy()
    out = out.rename(
        columns={
            "dau": "current_dau",
            "dau_legacy_any_event": "candidate_dau",
            "paid_subscription": "current_paid_subscription",
            "revenue_gbp": "current_revenue_gbp",
        }
    )
    out["candidate_paid_subscription"] = out["current_paid_subscription"]
    out["candidate_revenue_gbp"] = out["current_revenue_gbp"]
    out["dau_delta_users"] = out["candidate_dau"] - out["current_dau"]
    out["dau_relative_delta"] = out["dau_delta_users"] / out["current_dau"].replace(0, pd.NA)
    out["paid_delta"] = out["candidate_paid_subscription"] - out["current_paid_subscription"]
    out["revenue_delta_gbp"] = out["candidate_revenue_gbp"] - out["current_revenue_gbp"]
    return out.sort_values(["product", "date"]).reset_index(drop=True)


def summarise_dau_shadow_replay(replay: pd.DataFrame) -> pd.DataFrame:
    """Summarise product-level metric movement from a shadow replay."""
    required = {
        "product",
        "current_dau",
        "candidate_dau",
        "dau_relative_delta",
        "paid_delta",
        "revenue_delta_gbp",
    }
    missing = required.difference(replay.columns)
    if missing:
        raise ValueError(f"Missing replay columns: {sorted(missing)}")

    rows: list[dict[str, Any]] = []
    for product, group in replay.groupby("product", sort=True):
        current_total = float(group["current_dau"].sum())
        candidate_total = float(group["candidate_dau"].sum())
        rows.append(
            {
                "product": product,
                "days": int(len(group)),
                "current_dau_total": current_total,
                "candidate_dau_total": candidate_total,
                "portfolio_weighted_dau_delta_pct": (
                    candidate_total / current_total - 1.0 if current_total else float("nan")
                ),
                "max_daily_abs_dau_delta_pct": float(group["dau_relative_delta"].abs().dropna().max()),
                "max_abs_paid_delta": float(group["paid_delta"].abs().max()),
                "max_abs_revenue_delta_gbp": float(group["revenue_delta_gbp"].abs().max()),
            }
        )
    return pd.DataFrame(rows).sort_values("product").reset_index(drop=True)


def decide_migration(
    proposal: str,
    classification: ContractClassification,
    *,
    max_abs_metric_delta_pct: float,
    forecast_eligibility_changed: bool,
    tolerance: float = MIGRATION_TOLERANCE,
) -> MigrationDecision:
    """Apply non-compensatory migration gates."""
    producer_gate = bool(classification.producer_compatible)
    metric_gate = bool(max_abs_metric_delta_pct <= tolerance)
    forecast_gate = not bool(forecast_eligibility_changed)
    approved = bool(producer_gate and metric_gate and forecast_gate)
    action = "APPROVE" if approved else "WITHHOLD"

    failures: list[str] = []
    if not producer_gate:
        failures.append("existing producers are not contract-compatible")
    if not metric_gate:
        failures.append(
            f"shadow metric movement {max_abs_metric_delta_pct:.4f} exceeds tolerance {tolerance:.4f}"
        )
    if not forecast_gate:
        failures.append("forecast eligibility changes under the candidate metric")
    reason = "all non-compensatory migration gates passed" if approved else "; ".join(failures)

    return MigrationDecision(
        proposal=proposal,
        classification=classification.classification,
        producer_compatible_gate=producer_gate,
        metric_invariance_gate=metric_gate,
        forecast_eligibility_gate=forecast_gate,
        approved=approved,
        action=action,
        reason=reason,
    )


def contract_registry() -> dict[str, Any]:
    current = event_contract()
    proposals = migration_proposals()
    return {
        "current": current,
        "proposals": {
            name: {
                "contract": proposal,
                "classification": asdict(classify_event_contract_change(current, proposal)),
            }
            for name, proposal in sorted(proposals.items())
        },
    }
