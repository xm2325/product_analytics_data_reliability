from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from typing import Iterable

import numpy as np
import pandas as pd

from .config import DEFAULT_SEED, PRODUCTS, ProductConfig


EVENT_COLUMNS = [
    "event_id",
    "user_id",
    "product",
    "event_type",
    "event_ts",
    "platform",
    "source",
    "revenue_gbp",
]


def generate_events(
    days: int = 120,
    seed: int = DEFAULT_SEED,
    products: Iterable[ProductConfig] = PRODUCTS,
    inject_faults: bool = True,
) -> pd.DataFrame:
    """Generate a deterministic subscription + product-activity event stream.

    Each acquired user emits `first_open` and an explicit `app_open` on day 0.
    Later `app_open` events are generated from a product-specific decaying
    return probability for up to `activity_horizon_days`. This makes active-use
    metrics distinct from commercial funnel events.

    Fault injection deliberately adds duplicate purchase events and malformed
    identity rows so validation behaviour can be tested.
    """
    rng = np.random.default_rng(seed)
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    rows: list[dict] = []
    event_seq = 0
    user_seq = 0

    for product in products:
        for day in range(days):
            n_users = int(rng.poisson(product.daily_acquisition))
            for _ in range(n_users):
                user_seq += 1
                user_id = f"u{user_seq:08d}"
                platform = rng.choice(["ios", "android", "web"], p=[0.43, 0.39, 0.18])
                source = rng.choice(["organic", "paid_search", "social", "referral"], p=[0.46, 0.25, 0.19, 0.10])
                base_ts = start + timedelta(days=day, minutes=int(rng.integers(0, 1440)))

                def add(event_type: str, ts: datetime, revenue: float = 0.0) -> None:
                    nonlocal event_seq
                    event_seq += 1
                    rows.append(
                        {
                            "event_id": f"e{event_seq:010d}",
                            "user_id": user_id,
                            "product": product.name,
                            "event_type": event_type,
                            "event_ts": ts,
                            "platform": platform,
                            "source": source,
                            "revenue_gbp": float(revenue),
                        }
                    )

                add("first_open", base_ts)
                add("app_open", base_ts + timedelta(minutes=1))

                # One binary daily-return opportunity per user/day is enough to
                # create a clear activity signal without pretending to model
                # session frequency. Day 0 activity is guaranteed above.
                for lag in range(1, product.activity_horizon_days + 1):
                    return_probability = product.activity_floor + product.activity_peak * np.exp(
                        -lag / product.activity_decay_days
                    )
                    return_probability = float(np.clip(return_probability, 0.0, 1.0))
                    if rng.random() < return_probability:
                        activity_ts = start + timedelta(
                            days=day + lag,
                            minutes=int(rng.integers(0, 1440)),
                        )
                        add("app_open", activity_ts)

                if rng.random() < product.trial_rate:
                    trial_ts = base_ts + timedelta(hours=int(rng.integers(1, 36)))
                    add("trial_start", trial_ts)
                    if rng.random() < product.paid_given_trial:
                        paid_ts = trial_ts + timedelta(days=int(rng.integers(1, 8)))
                        add("paid_subscription", paid_ts)
                        add("purchase", paid_ts + timedelta(minutes=1), product.monthly_price_gbp)

    frame = pd.DataFrame(rows, columns=EVENT_COLUMNS)
    frame["event_ts"] = pd.to_datetime(frame["event_ts"], utc=True)

    if inject_faults and not frame.empty:
        purchase_idx = frame.index[frame["event_type"].eq("purchase")].to_numpy()
        if len(purchase_idx):
            # Duplicate a controlled sample while preserving event_id. These
            # rows should inflate raw revenue and be removed by certification.
            n_dup = max(1, int(round(0.10 * len(purchase_idx))))
            dup_idx = rng.choice(purchase_idx, size=n_dup, replace=False)
            duplicates = frame.loc[dup_idx].copy()
            frame = pd.concat([frame, duplicates], ignore_index=True)

        n_identity_faults = max(1, int(round(0.002 * len(frame))))
        bad_idx = rng.choice(frame.index.to_numpy(), size=n_identity_faults, replace=False)
        frame.loc[bad_idx, "user_id"] = None

    return frame.sort_values("event_ts", kind="stable").reset_index(drop=True)


def product_config_frame(products: Iterable[ProductConfig] = PRODUCTS) -> pd.DataFrame:
    return pd.DataFrame([asdict(p) for p in products])
