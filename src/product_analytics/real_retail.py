from __future__ import annotations

from dataclasses import asdict
from hashlib import sha256
from pathlib import Path
from urllib.request import Request, urlopen
import json
import zipfile

import numpy as np
import pandas as pd

from .forecasting import (
    ForecastPlanningGate,
    evaluate_forecast_plan,
    rolling_origin_seasonal_naive,
)

UCI_ONLINE_RETAIL_II_URL = (
    "https://archive.ics.uci.edu/static/public/502/online%2Bretail%2Bii.zip"
)
UCI_ONLINE_RETAIL_II_DOI = "10.24432/C5CG6D"
UCI_ONLINE_RETAIL_II_LICENSE = "CC BY 4.0"
REAL_DATA_METRIC_TOLERANCE = 0.01

_COLUMN_ALIASES = {
    "invoice_no": ("Invoice", "InvoiceNo"),
    "stock_code": ("StockCode",),
    "description": ("Description",),
    "quantity": ("Quantity",),
    "invoice_ts": ("InvoiceDate",),
    "unit_price_gbp": ("Price", "UnitPrice"),
    "customer_id": ("Customer ID", "CustomerID"),
    "country": ("Country",),
}


def _hash_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download_source(destination: Path, source_url: str = UCI_ONLINE_RETAIL_II_URL) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() and destination.stat().st_size > 0:
        return destination
    request = Request(source_url, headers={"User-Agent": "product-analytics-data-reliability/0.36"})
    with urlopen(request, timeout=120) as response, destination.open("wb") as handle:
        while True:
            chunk = response.read(1024 * 1024)
            if not chunk:
                break
            handle.write(chunk)
    if destination.stat().st_size == 0:
        raise RuntimeError("Downloaded UCI archive is empty")
    return destination


def extract_workbook(archive_path: Path, destination_dir: Path) -> Path:
    destination_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive_path) as archive:
        candidates = [name for name in archive.namelist() if name.lower().endswith(".xlsx")]
        if len(candidates) != 1:
            raise ValueError(f"Expected exactly one XLSX in archive, found {candidates}")
        member = candidates[0]
        archive.extract(member, path=destination_dir)
    return destination_dir / member


def _resolve_columns(columns: list[str]) -> dict[str, str]:
    available = {str(column).strip(): str(column) for column in columns}
    resolved: dict[str, str] = {}
    for canonical, aliases in _COLUMN_ALIASES.items():
        match = next((available[alias] for alias in aliases if alias in available), None)
        if match is None:
            raise ValueError(f"Missing source field for {canonical!r}; aliases={aliases}")
        resolved[canonical] = match
    return resolved


def _normalise_customer_id(series: pd.Series) -> pd.Series:
    values = series.astype("string").str.strip()
    values = values.replace({"": pd.NA, "nan": pd.NA, "None": pd.NA, "<NA>": pd.NA})
    values = values.str.replace(r"\.0$", "", regex=True)
    return values


def load_workbook(workbook_path: Path) -> tuple[pd.DataFrame, list[str]]:
    sheets = pd.read_excel(workbook_path, sheet_name=None, engine="openpyxl")
    if not sheets:
        raise ValueError("Workbook has no sheets")
    frames: list[pd.DataFrame] = []
    for sheet_name, raw in sheets.items():
        resolved = _resolve_columns([str(c) for c in raw.columns])
        frame = pd.DataFrame(
            {
                "invoice_no": raw[resolved["invoice_no"]],
                "stock_code": raw[resolved["stock_code"]],
                "description": raw[resolved["description"]],
                "quantity": raw[resolved["quantity"]],
                "invoice_ts": raw[resolved["invoice_ts"]],
                "unit_price_gbp": raw[resolved["unit_price_gbp"]],
                "customer_id": raw[resolved["customer_id"]],
                "country": raw[resolved["country"]],
            }
        )
        frame["source_sheet"] = str(sheet_name)
        frames.append(frame)
    canonical = pd.concat(frames, ignore_index=True)
    canonical.insert(0, "source_row_id", np.arange(len(canonical), dtype=np.int64))
    canonical["invoice_no"] = canonical["invoice_no"].astype("string").str.strip()
    canonical["stock_code"] = canonical["stock_code"].astype("string").str.strip()
    canonical["description"] = canonical["description"].astype("string").str.strip()
    canonical["quantity"] = pd.to_numeric(canonical["quantity"], errors="coerce")
    canonical["invoice_ts"] = pd.to_datetime(canonical["invoice_ts"], errors="coerce")
    canonical["unit_price_gbp"] = pd.to_numeric(canonical["unit_price_gbp"], errors="coerce")
    canonical["customer_id"] = _normalise_customer_id(canonical["customer_id"])
    canonical["country"] = canonical["country"].astype("string").str.strip()
    canonical["is_cancellation"] = canonical["invoice_no"].fillna("").str.upper().str.startswith("C")
    canonical["line_value_gbp"] = canonical["quantity"] * canonical["unit_price_gbp"]
    canonical["is_purchase_line"] = (
        canonical["invoice_no"].notna()
        & canonical["invoice_ts"].notna()
        & ~canonical["is_cancellation"]
        & canonical["quantity"].gt(0)
        & canonical["unit_price_gbp"].gt(0)
    )
    canonical["is_identified_purchase_line"] = canonical["is_purchase_line"] & canonical["customer_id"].notna()
    return canonical, [str(name) for name in sheets]


def quality_report(canonical: pd.DataFrame, sheets: list[str]) -> dict[str, object]:
    valid_ts = canonical["invoice_ts"].dropna()
    return {
        "source_rows": int(len(canonical)),
        "source_sheets": sheets,
        "date_min": valid_ts.min().isoformat() if len(valid_ts) else None,
        "date_max": valid_ts.max().isoformat() if len(valid_ts) else None,
        "distinct_invoices": int(canonical["invoice_no"].nunique(dropna=True)),
        "distinct_stock_codes": int(canonical["stock_code"].nunique(dropna=True)),
        "distinct_countries": int(canonical["country"].nunique(dropna=True)),
        "missing_customer_rows": int(canonical["customer_id"].isna().sum()),
        "missing_invoice_timestamp_rows": int(canonical["invoice_ts"].isna().sum()),
        "cancellation_rows": int(canonical["is_cancellation"].sum()),
        "nonpositive_quantity_rows": int(canonical["quantity"].le(0).fillna(False).sum()),
        "nonpositive_unit_price_rows": int(canonical["unit_price_gbp"].le(0).fillna(False).sum()),
        "purchase_line_rows": int(canonical["is_purchase_line"].sum()),
        "identified_purchase_line_rows": int(canonical["is_identified_purchase_line"].sum()),
        "exact_duplicate_rows_excluding_source_id": int(
            canonical.drop(columns=["source_row_id"]).duplicated().sum()
        ),
    }


def build_daily_metrics(canonical: pd.DataFrame) -> pd.DataFrame:
    purchases = canonical.loc[canonical["is_purchase_line"]].copy()
    if purchases.empty:
        raise ValueError("No valid purchase lines found")
    purchases["date"] = purchases["invoice_ts"].dt.normalize()
    purchases["purchase_revenue_gbp"] = purchases["line_value_gbp"].astype(float)

    daily = (
        purchases.groupby("date", as_index=False)
        .agg(
            revenue_gbp=("purchase_revenue_gbp", "sum"),
            orders=("invoice_no", "nunique"),
            units=("quantity", "sum"),
            purchase_lines=("source_row_id", "size"),
        )
    )
    identified = purchases.loc[purchases["customer_id"].notna()]
    customers = (
        identified.groupby("date")["customer_id"].nunique().rename("active_customers")
    )
    daily = daily.set_index("date").join(customers, how="left")
    full_index = pd.date_range(daily.index.min(), daily.index.max(), freq="D")
    daily = daily.reindex(full_index, fill_value=0.0)
    daily.index.name = "date"
    daily = daily.reset_index()
    daily["date"] = daily["date"].dt.date
    for column in ["orders", "units", "purchase_lines", "active_customers"]:
        daily[column] = daily[column].astype(float)
    return daily


def semantic_comparison(canonical: pd.DataFrame, tolerance: float = REAL_DATA_METRIC_TOLERANCE) -> pd.DataFrame:
    purchases = canonical.loc[canonical["is_purchase_line"]]
    current_revenue = float(purchases["line_value_gbp"].sum())
    signed_rows = canonical.loc[
        canonical["invoice_ts"].notna()
        & canonical["quantity"].notna()
        & canonical["unit_price_gbp"].notna()
    ]
    candidate_revenue = float(signed_rows["line_value_gbp"].sum())

    current_customers = float(
        canonical.loc[canonical["is_identified_purchase_line"], "customer_id"].nunique()
    )
    candidate_customers = float(
        canonical.loc[
            canonical["invoice_ts"].notna() & canonical["customer_id"].notna(),
            "customer_id",
        ].nunique()
    )

    rows = [
        {
            "metric": "revenue_gbp",
            "current_definition": "positive non-cancelled purchase lines",
            "candidate_definition": "signed value of all timestamped transaction lines",
            "current_value": current_revenue,
            "candidate_value": candidate_revenue,
        },
        {
            "metric": "active_customer_population",
            "current_definition": "customers with at least one valid purchase line",
            "candidate_definition": "customers with any timestamped transaction line",
            "current_value": current_customers,
            "candidate_value": candidate_customers,
        },
    ]
    frame = pd.DataFrame(rows)
    frame["relative_delta"] = np.where(
        frame["current_value"].abs().gt(0),
        (frame["candidate_value"] - frame["current_value"]) / frame["current_value"].abs(),
        np.nan,
    )
    frame["tolerance"] = float(tolerance)
    frame["backward_compatible"] = frame["relative_delta"].abs().le(tolerance)
    frame["replacement_action"] = np.where(
        frame["backward_compatible"],
        "APPROVE_BACKWARD_COMPATIBLE",
        "WITHHOLD_AS_DROP_IN_REPLACEMENT",
    )
    return frame


def forecast_real_metrics(daily_metrics: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    gate = ForecastPlanningGate()
    backtests: list[pd.DataFrame] = []
    evaluations: list[dict[str, object]] = []
    for metric in ["revenue_gbp", "orders", "units", "active_customers"]:
        backtest = rolling_origin_seasonal_naive(daily_metrics, metric)
        backtest.insert(0, "metric", metric)
        backtests.append(backtest)
        evaluation = evaluate_forecast_plan(metric, backtest, gate)
        evaluations.append(asdict(evaluation))
    return pd.concat(backtests, ignore_index=True), pd.DataFrame(evaluations)


def source_provenance(
    archive_path: Path,
    workbook_path: Path,
    sheets: list[str],
    source_url: str = UCI_ONLINE_RETAIL_II_URL,
) -> dict[str, object]:
    return {
        "dataset": "UCI Online Retail II",
        "source_url": source_url,
        "doi": UCI_ONLINE_RETAIL_II_DOI,
        "license": UCI_ONLINE_RETAIL_II_LICENSE,
        "source_description": "real transactions from a UK-based non-store online retailer",
        "archive_bytes": int(archive_path.stat().st_size),
        "archive_sha256": _hash_file(archive_path),
        "workbook_bytes": int(workbook_path.stat().st_size),
        "workbook_sha256": _hash_file(workbook_path),
        "sheets": sheets,
        "ingestion_timestamp_available": False,
        "late_arrival_or_watermark_claimed": False,
        "raw_source_committed_to_repository": False,
    }


def write_json(path: Path, payload: dict[str, object]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
