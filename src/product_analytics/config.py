from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ProductConfig:
    name: str
    daily_acquisition: float
    trial_rate: float
    paid_given_trial: float
    monthly_price_gbp: float


PRODUCTS = (
    ProductConfig("photo_editor", 92.0, 0.37, 0.49, 9.99),
    ProductConfig("notes_app", 78.0, 0.33, 0.52, 7.99),
    ProductConfig("file_transfer", 84.0, 0.29, 0.46, 11.99),
)

DEFAULT_SEED = 2206
