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
    "ingested_at",
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
    """Generate deterministic event-time and processing-time product data.

    Commercial/funnel randomness intentionally keeps the pre-v0.24 stream.
    Product activity and ingestion delay use separate RNG streams, so adding
    either system does not silently redraw acquisition, trial, paid or purchase
    outcomes.

    ``event_ts`` is when an action happened. ``ingested_at`` is when the data
    platform first received it. Most events arrive promptly; a small controlled
    tail arrives one to four days later so watermark/backfill behaviour can be
    tested without changing business truth.
    """
    commercial_rng = np.random.default_rng(seed)
    activity_rng = np.random.default_rng(seed + 1_000_003)
    ingestion_rng = np.random.default_rng(seed + 2_000_003)
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    rows: list[dict] = []
    event_seq = 0
    user_seq = 0

    for product in products:
        for day in range(days):
            n_users = int(commercial_rng.poisson(product.daily_acquisition))
            for _ in range(n_users):
                user_seq += 1
                user_id = f"u{user_seq:08d}"
                platform = commercial_rng.choice(["ios", "android", "web"], p=[0.43, 0.39, 0.18])
                source = commercial_rng.choice(
                    ["organic", "paid_search", "social", "referral"],
                    p=[0.46, 0.25, 0.19, 0.10],
                )
                base_ts = start + timedelta(days=day, minutes=int(commercial_rng.integers(0, 1440)))

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
                            "ingested_at": pd.NaT,
                            "platform": platform,
                            "source": source,
                            "revenue_gbp": float(revenue),
                        }
                    )

                add("first_open", base_ts)
                add("app_open", base_ts + timedelta(minutes=1))

                for lag in range(1, product.activity_horizon_days + 1):
                    return_probability = product.activity_floor + product.activity_peak * np.exp(
                        -lag / product.activity_decay_days
                    )
                    return_probability = float(np.clip(return_probability, 0.0, 1.0))
                    if activity_rng.random() < return_probability:
                        activity_ts = start + timedelta(
                            days=day + lag,
                            minutes=int(activity_rng.integers(0, 1440)),
                        )
                        add("app_open", activity_ts)

                if commercial_rng.random() < product.trial_rate:
                    trial_ts = base_ts + timedelta(hours=int(commercial_rng.integers(1, 36)))
                    add("trial_start", trial_ts)
                    if commercial_rng.random() < product.paid_given_trial:
                        paid_ts = trial_ts + timedelta(days=int(commercial_rng.integers(1, 8)))
                        add("paid_subscription", paid_ts)
                        add("purchase", paid_ts + timedelta(minutes=1), product.monthly_price_gbp)

    frame = pd.DataFrame(rows, columns=EVENT_COLUMNS)
    frame["event_ts"] = pd.to_datetime(frame["event_ts"], utc=True)

    # Separate processing-time stream. The discrete tail is deliberate:
    # 0.5% of events arrive ~4 days late and therefore breach a 48-hour
    # watermark. Jitter avoids every event sharing the same arrival offset.
    if not frame.empty:
        delay_hours = ingestion_rng.choice(
            np.array([0, 1, 2, 6, 24, 48, 96], dtype=int),
            size=len(frame),
            p=[0.55, 0.20, 0.10, 0.08, 0.045, 0.020, 0.005],
        )
        delay_minutes = ingestion_rng.integers(0, 60, size=len(frame))
        frame["ingested_at"] = frame["event_ts"] + pd.to_timedelta(delay_hours, unit="h") + pd.to_timedelta(
            delay_minutes, unit="m"
        )

    if inject_faults and not frame.empty:
        purchase_idx = frame.index[frame["event_type"].eq("purchase")].to_numpy()
        if len(purchase_idx):
            n_dup = max(1, int(round(0.10 * len(purchase_idx))))
            dup_idx = commercial_rng.choice(purchase_idx, size=n_dup, replace=False)
            # Exact transport duplicate: event id and ingestion time are kept.
            duplicates = frame.loc[dup_idx].copy()
            frame = pd.concat([frame, duplicates], ignore_index=True)

        identity_candidates = frame.index[~frame["event_type"].eq("app_open")].to_numpy()
        n_identity_faults = max(1, int(round(0.002 * len(identity_candidates))))
        bad_idx = commercial_rng.choice(identity_candidates, size=n_identity_faults, replace=False)
        frame.loc[bad_idx, "user_id"] = None

    return frame.sort_values(["event_ts", "event_id"], kind="stable").reset_index(drop=True)


def product_config_frame(products: Iterable[ProductConfig] = PRODUCTS) -> pd.DataFrame:
    return pd.DataFrame([asdict(p) for p in products])
