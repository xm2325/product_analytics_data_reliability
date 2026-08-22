from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ProductConfig:
    name: str
    daily_acquisition: float
    trial_rate: float
    paid_given_trial: float
    monthly_price_gbp: float
    activity_peak: float = 0.32
    activity_floor: float = 0.06
    activity_decay_days: float = 18.0
    activity_horizon_days: int = 30


PRODUCTS = (
    ProductConfig("photo_editor", 92.0, 0.37, 0.49, 9.99, 0.32, 0.06, 16.0, 30),
    ProductConfig("notes_app", 78.0, 0.33, 0.52, 7.99, 0.38, 0.09, 28.0, 30),
    ProductConfig("file_transfer", 84.0, 0.29, 0.46, 11.99, 0.27, 0.04, 12.0, 30),
)

DEFAULT_SEED = 2206
