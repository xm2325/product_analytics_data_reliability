from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


REQUIRED_COLUMNS = {
    "event_id",
    "user_id",
    "product",
    "event_type",
    "event_ts",
    "revenue_gbp",
}


@dataclass(frozen=True)
class QualityReport:
    rows_raw: int
    duplicate_event_rows: int
    missing_identity_rows: int
    invalid_timestamp_rows: int
    negative_revenue_rows: int
    rows_certified: int


def certify_events(events: pd.DataFrame) -> tuple[pd.DataFrame, QualityReport]:
    missing = REQUIRED_COLUMNS.difference(events.columns)
    if missing:
        raise ValueError(f"Missing required columns: {sorted(missing)}")

    df = events.copy()
    parsed_ts = pd.to_datetime(df["event_ts"], errors="coerce", utc=True)
    duplicate = df.duplicated("event_id", keep="first")
    missing_identity = df["user_id"].isna() | df["user_id"].astype("string").str.strip().eq("")
    invalid_ts = parsed_ts.isna()
    negative_revenue = pd.to_numeric(df["revenue_gbp"], errors="coerce").fillna(-1).lt(0)

    valid = ~(duplicate | missing_identity | invalid_ts | negative_revenue)
    certified = df.loc[valid].copy()
    certified["event_ts"] = parsed_ts.loc[valid]
    certified["revenue_gbp"] = pd.to_numeric(certified["revenue_gbp"], errors="raise").astype(float)
    certified = certified.sort_values(["event_ts", "event_id"]).reset_index(drop=True)

    report = QualityReport(
        rows_raw=len(df),
        duplicate_event_rows=int(duplicate.sum()),
        missing_identity_rows=int(missing_identity.sum()),
        invalid_timestamp_rows=int(invalid_ts.sum()),
        negative_revenue_rows=int(negative_revenue.sum()),
        rows_certified=len(certified),
    )
    return certified, report


def reconcile_revenue(raw: pd.DataFrame, certified: pd.DataFrame) -> pd.DataFrame:
    """Compare raw and certified purchase revenue by product."""
    def revenue(frame: pd.DataFrame, label: str) -> pd.Series:
        x = frame.loc[frame["event_type"].eq("purchase")].copy()
        return x.groupby("product")["revenue_gbp"].sum().rename(label)

    out = pd.concat([revenue(raw, "raw_revenue_gbp"), revenue(certified, "certified_revenue_gbp")], axis=1).fillna(0.0)
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
