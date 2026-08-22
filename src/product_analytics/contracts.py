from __future__ import annotations

from .config import PRODUCTS
from .quality import ALLOWED_EVENT_TYPES, REQUIRED_COLUMNS


def event_contract() -> dict[str, object]:
    """Machine-readable contract for the compact public event model."""
    return {
        "version": "1.2",
        "grain": "one product event per row",
        "required_columns": sorted(REQUIRED_COLUMNS),
        "generated_processing_time_column": "ingested_at",
        "legacy_processing_time_fallback": "if ingested_at is absent, certification treats arrival time as event_ts",
        "optional_dimensions": ["platform", "source"],
        "allowed_products": sorted(product.name for product in PRODUCTS),
        "allowed_event_types": sorted(ALLOWED_EVENT_TYPES),
        "activity_event": "app_open",
        "rules": {
            "event_id": "non-null event identifier; duplicate identifiers are rejected after the first row",
            "user_id": "non-null, non-empty identity",
            "event_ts": "UTC-parseable event-time timestamp",
            "ingested_at": "UTC-parseable processing-time timestamp on or after event_ts for v0.26 generated sources",
            "revenue_gbp": "numeric and non-negative",
            "revenue_scope": "non-zero revenue is allowed only on purchase events",
            "active_use": "daily active use is identified by app_open rather than arbitrary funnel/commercial events",
        },
    }
