from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from .config import PRODUCTS


REQUIRED_COLUMNS = {
    "event_id",
    "user_id",
    "product",
    "event_type",
    "event_ts",
    "revenue_gbp",
}
ALLOWED_PRODUCTS = {product.name for product in PRODUCTS}
ALLOWED_EVENT_TYPES = {"first_open", "app_open", "trial_start", "paid_subscription", "purchase"}


@dataclass(frozen=True)
class QualityReport:
    rows_raw: int
    duplicate_event_rows: int
    missing_identity_rows: int
    invalid_timestamp_rows: int
    invalid_ingestion_timestamp_rows: int
    ingestion_before_event_rows: int
    invalid_revenue_rows: int
    unknown_product_rows: int
    unknown_event_type_rows: int
    non_purchase_revenue_rows: int
    rows_rejected: int
    rows_certified: int


def _append_reason(reason: pd.Series, mask: pd.Series, label: str) -> pd.Series:
    prefix = reason.where(reason.eq(""), reason + ";")
    return reason.where(~mask, prefix + label)


def certify_events_with_rejects(
    events: pd.DataFrame,
) -> tuple[pd.DataFrame, QualityReport, pd.DataFrame]:
    """Certify events while preserving row-level rejection evidence.

    Current generated sources carry explicit ``ingested_at`` processing time.
    Legacy callers may omit it; those rows are treated as immediate arrivals at
    event_ts and retain the pre-v0.26 error taxonomy.
    """
    missing = REQUIRED_COLUMNS.difference(events.columns)
    if missing:
        raise ValueError(f"Missing required columns: {sorted(missing)}")

    df = events.copy()
    parsed_ts = pd.to_datetime(df["event_ts"], errors="coerce", utc=True)
    has_explicit_ingestion = "ingested_at" in df.columns
    if has_explicit_ingestion:
        parsed_ingested = pd.to_datetime(df["ingested_at"], errors="coerce", utc=True)
    else:
        parsed_ingested = parsed_ts.copy()
        df["ingested_at"] = parsed_ingested
    revenue_numeric = pd.to_numeric(df["revenue_gbp"], errors="coerce")

    duplicate = df.duplicated("event_id", keep="first")
    missing_identity = df["user_id"].isna() | df["user_id"].astype("string").str.strip().eq("")
    invalid_ts = parsed_ts.isna()
    if has_explicit_ingestion:
        invalid_ingested = parsed_ingested.isna()
        ingestion_before_event = parsed_ts.notna() & parsed_ingested.notna() & parsed_ingested.lt(parsed_ts)
    else:
        invalid_ingested = pd.Series(False, index=df.index)
        ingestion_before_event = pd.Series(False, index=df.index)
    invalid_revenue = revenue_numeric.isna() | revenue_numeric.lt(0)
    unknown_product = ~df["product"].isin(ALLOWED_PRODUCTS)
    unknown_event_type = ~df["event_type"].isin(ALLOWED_EVENT_TYPES)
    non_purchase_revenue = ~df["event_type"].eq("purchase") & revenue_numeric.fillna(0.0).ne(0.0)

    reason = pd.Series("", index=df.index, dtype="string")
    for mask, label in [
        (duplicate, "duplicate_event_id"),
        (missing_identity, "missing_identity"),
        (invalid_ts, "invalid_timestamp"),
        (invalid_ingested, "invalid_ingestion_timestamp"),
        (ingestion_before_event, "ingestion_before_event"),
        (invalid_revenue, "invalid_revenue"),
        (unknown_product, "unknown_product"),
        (unknown_event_type, "unknown_event_type"),
        (non_purchase_revenue, "non_purchase_revenue"),
    ]:
        reason = _append_reason(reason, mask, label)

    valid = reason.eq("")
    certified = df.loc[valid].copy()
    certified["event_ts"] = parsed_ts.loc[valid]
    certified["ingested_at"] = parsed_ingested.loc[valid]
    certified["revenue_gbp"] = revenue_numeric.loc[valid].astype(float)
    certified = certified.sort_values(["event_ts", "event_id"], kind="stable").reset_index(drop=True)

    rejected = df.loc[~valid].copy()
    rejected["reject_reason"] = reason.loc[~valid].astype(str)
    rejected["event_ts_parsed"] = parsed_ts.loc[~valid]
    rejected["ingested_at_parsed"] = parsed_ingested.loc[~valid]
    rejected["revenue_gbp_parsed"] = revenue_numeric.loc[~valid]
    rejected = rejected.reset_index(drop=True)

    report = QualityReport(
        rows_raw=len(df),
        duplicate_event_rows=int(duplicate.sum()),
        missing_identity_rows=int(missing_identity.sum()),
        invalid_timestamp_rows=int(invalid_ts.sum()),
        invalid_ingestion_timestamp_rows=int(invalid_ingested.sum()),
        ingestion_before_event_rows=int(ingestion_before_event.sum()),
        invalid_revenue_rows=int(invalid_revenue.sum()),
        unknown_product_rows=int(unknown_product.sum()),
        unknown_event_type_rows=int(unknown_event_type.sum()),
        non_purchase_revenue_rows=int(non_purchase_revenue.sum()),
        rows_rejected=int((~valid).sum()),
        rows_certified=len(certified),
    )
    return certified, report, rejected


def certify_events(events: pd.DataFrame) -> tuple[pd.DataFrame, QualityReport]:
    """Backward-compatible two-output certification API."""
    certified, report, _ = certify_events_with_rejects(events)
    return certified, report


def reconcile_revenue(raw: pd.DataFrame, certified: pd.DataFrame) -> pd.DataFrame:
    """Compare raw and certified purchase revenue by product."""

    def revenue(frame: pd.DataFrame, label: str) -> pd.Series:
        x = frame.loc[frame["event_type"].eq("purchase")].copy()
        values = pd.to_numeric(x["revenue_gbp"], errors="coerce").fillna(0.0)
        return values.groupby(x["product"]).sum().rename(label)

    out = pd.concat(
        [revenue(raw, "raw_revenue_gbp"), revenue(certified, "certified_revenue_gbp")],
        axis=1,
    ).fillna(0.0)
    out["overstatement_gbp"] = out["raw_revenue_gbp"] - out["certified_revenue_gbp"]
    denominator = out["certified_revenue_gbp"].replace(0, pd.NA)
    out["overstatement_pct"] = 100.0 * out["overstatement_gbp"] / denominator
    return out.reset_index()


def idempotent_backfill(current: pd.DataFrame, corrections: pd.DataFrame, key: str = "event_id") -> pd.DataFrame:
    """Apply replacement rows by key; rerunning the same correction is a no-op."""
    if key not in current or key not in corrections:
        raise ValueError(f"Both frames must contain {key!r}")
    base = current.set_index(key, drop=False).copy()
    patch = corrections.set_index(key, drop=False)
    for idx, row in patch.iterrows():
        base.loc[idx] = row
    return base.reset_index(drop=True).sort_values(key).reset_index(drop=True)
