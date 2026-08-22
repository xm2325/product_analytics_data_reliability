from __future__ import annotations

from .config import PRODUCTS
from .quality import ALLOWED_EVENT_TYPES, REQUIRED_COLUMNS


def event_contract() -> dict[str, object]:
    """Machine-readable contract for the compact public event model."""
    return {
        "version": "1.1",
        "grain": "one product event per row",
        "required_columns": sorted(REQUIRED_COLUMNS),
        "optional_dimensions": ["platform", "source"],
        "allowed_products": sorted(product.name for product in PRODUCTS),
        "allowed_event_types": sorted(ALLOWED_EVENT_TYPES),
        "activity_event": "app_open",
        "rules": {
            "event_id": "non-null event identifier; duplicate identifiers are rejected after the first row",
            "user_id": "non-null, non-empty identity",
            "event_ts": "UTC-parseable timestamp",
            "revenue_gbp": "numeric and non-negative",
            "revenue_scope": "non-zero revenue is allowed only on purchase events",
            "active_use": "daily active use is identified by app_open rather than arbitrary funnel/commercial events",
        },
    }
