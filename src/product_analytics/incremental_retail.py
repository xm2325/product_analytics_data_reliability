from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from time import perf_counter
import json

import duckdb
import numpy as np
import pandas as pd


@dataclass(frozen=True)
class IncrementalRunStats:
    processed_partitions: int
    skipped_partitions: int
    rows_scanned: int
    elapsed_seconds: float


class SimulatedInterruption(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _load_state(path: Path) -> dict[str, object]:
    if not path.exists():
        return {"version": "0.37.0", "partitions": {}}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("version") != "0.37.0":
        raise ValueError(f"Unsupported incremental state version: {payload.get('version')}")
    payload.setdefault("partitions", {})
    return payload


def canonical_partition_key(invoice_ts: pd.Series) -> pd.Series:
    parsed = pd.to_datetime(invoice_ts, errors="coerce")
    key = parsed.dt.to_period("M").astype("string")
    return key.fillna("_invalid_ts")


def write_canonical_partitions(canonical: pd.DataFrame, output_dir: Path) -> pd.DataFrame:
    """Write immutable month partitions once after source adaptation.

    Parquet is written by DuckDB so the project does not need a second parquet
    dependency. Every canonical row belongs to exactly one partition, including
    malformed timestamps via the explicit `_invalid_ts` partition.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    frame = canonical.copy()
    frame["partition_key"] = canonical_partition_key(frame["invoice_ts"])
    rows: list[dict[str, object]] = []
    con = duckdb.connect()
    try:
        for key in sorted(frame["partition_key"].unique().tolist()):
            subset = frame.loc[frame["partition_key"] == key].drop(columns=["partition_key"])
            target = output_dir / f"{key}.parquet"
            con.register("partition_frame", subset)
            con.execute(
                "COPY (SELECT * FROM partition_frame ORDER BY source_row_id) "
                f"TO '{target.as_posix()}' (FORMAT PARQUET, COMPRESSION ZSTD)"
            )
            con.unregister("partition_frame")
            rows.append(
                {
                    "partition_key": key,
                    "rows": int(len(subset)),
                    "bytes": int(target.stat().st_size),
                    "sha256": sha256_file(target),
                }
            )
    finally:
        con.close()
    manifest = pd.DataFrame(rows).sort_values("partition_key").reset_index(drop=True)
    if int(manifest["rows"].sum()) != len(canonical):
        raise AssertionError("Canonical partition row count does not reconcile to source rows")
    return manifest


def _aggregate_partition(source_path: Path, output_path: Path) -> int:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    try:
        rows = int(con.execute("SELECT count(*) FROM read_parquet(?)", [str(source_path)]).fetchone()[0])
        con.execute(
            """
            COPY (
                SELECT
                    CAST(invoice_ts AS DATE) AS date,
                    ROUND(SUM(CASE WHEN is_purchase_line THEN line_value_gbp ELSE 0 END), 6) AS revenue_gbp,
                    COUNT(DISTINCT CASE WHEN is_purchase_line THEN invoice_no END) AS orders,
                    COALESCE(SUM(CASE WHEN is_purchase_line THEN quantity ELSE 0 END), 0) AS units,
                    SUM(CASE WHEN is_purchase_line THEN 1 ELSE 0 END) AS purchase_lines,
                    COUNT(DISTINCT CASE
                        WHEN is_purchase_line AND customer_id IS NOT NULL THEN customer_id
                    END) AS active_customers
                FROM read_parquet(?)
                WHERE invoice_ts IS NOT NULL
                GROUP BY 1
                ORDER BY 1
            ) TO ? (FORMAT PARQUET, COMPRESSION ZSTD)
            """,
            [str(source_path), str(source_path), str(output_path)],
        )
        return rows
    finally:
        con.close()


def run_incremental(
    source_dir: Path,
    metric_dir: Path,
    state_path: Path,
    *,
    stop_after_processed: int | None = None,
) -> IncrementalRunStats:
    """Process only missing, changed or invalidated monthly partitions.

    A partition is reusable only when both its source SHA and its materialised
    metric SHA agree with durable state. State is written after each successful
    partition so an interrupted run can resume without replaying completed work.
    """
    started = perf_counter()
    state = _load_state(state_path)
    partitions: dict[str, dict[str, object]] = state["partitions"]  # type: ignore[assignment]
    processed = skipped = rows_scanned = 0

    source_paths = sorted(source_dir.glob("*.parquet"))
    if not source_paths:
        raise ValueError(f"No canonical parquet partitions found in {source_dir}")

    for source_path in source_paths:
        key = source_path.stem
        metric_path = metric_dir / f"{key}.parquet"
        source_sha = sha256_file(source_path)
        previous = partitions.get(key)
        reusable = bool(
            previous
            and previous.get("source_sha256") == source_sha
            and metric_path.exists()
            and previous.get("metric_sha256") == sha256_file(metric_path)
            and previous.get("status") == "complete"
        )
        if reusable:
            skipped += 1
            continue

        rows = _aggregate_partition(source_path, metric_path)
        rows_scanned += rows
        processed += 1
        partitions[key] = {
            "status": "complete",
            "source_path": source_path.name,
            "source_rows": rows,
            "source_sha256": source_sha,
            "metric_path": metric_path.name,
            "metric_sha256": sha256_file(metric_path),
        }
        state["partitions"] = partitions
        _write_json(state_path, state)

        if stop_after_processed is not None and processed >= stop_after_processed:
            raise SimulatedInterruption(
                f"simulated interruption after {processed} newly processed partitions"
            )

    return IncrementalRunStats(
        processed_partitions=processed,
        skipped_partitions=skipped,
        rows_scanned=rows_scanned,
        elapsed_seconds=perf_counter() - started,
    )


def materialise_incremental_daily(metric_dir: Path) -> pd.DataFrame:
    paths = sorted(metric_dir.glob("*.parquet"))
    if not paths:
        raise ValueError(f"No metric partitions found in {metric_dir}")
    con = duckdb.connect()
    try:
        daily = con.execute(
            """
            SELECT
                date,
                ROUND(SUM(revenue_gbp), 6) AS revenue_gbp,
                SUM(orders)::BIGINT AS orders,
                SUM(units)::DOUBLE AS units,
                SUM(purchase_lines)::BIGINT AS purchase_lines,
                SUM(active_customers)::BIGINT AS active_customers
            FROM read_parquet(?)
            GROUP BY 1
            ORDER BY 1
            """,
            [[str(path) for path in paths]],
        ).df()
    finally:
        con.close()

    if daily.empty:
        raise ValueError("Incremental metric store is empty")
    daily["date"] = pd.to_datetime(daily["date"])
    full = pd.DataFrame({"date": pd.date_range(daily["date"].min(), daily["date"].max(), freq="D")})
    daily = full.merge(daily, on="date", how="left").fillna(0)
    daily["date"] = daily["date"].dt.date
    for column in ["orders", "purchase_lines", "active_customers"]:
        daily[column] = daily[column].astype(np.int64)
    daily["units"] = daily["units"].astype(float)
    daily["revenue_gbp"] = daily["revenue_gbp"].astype(float).round(6)
    return daily


def normalise_full_daily(daily: pd.DataFrame) -> pd.DataFrame:
    result = daily.copy()
    result["date"] = pd.to_datetime(result["date"]).dt.date
    result["revenue_gbp"] = result["revenue_gbp"].astype(float).round(6)
    for column in ["orders", "purchase_lines", "active_customers"]:
        result[column] = result[column].astype(np.int64)
    result["units"] = result["units"].astype(float)
    return result[["date", "revenue_gbp", "orders", "units", "purchase_lines", "active_customers"]]


def assert_daily_parity(full_daily: pd.DataFrame, incremental_daily: pd.DataFrame) -> None:
    expected = normalise_full_daily(full_daily).reset_index(drop=True)
    observed = normalise_full_daily(incremental_daily).reset_index(drop=True)
    pd.testing.assert_frame_equal(expected, observed, check_exact=True)


def state_partition_frame(state_path: Path) -> pd.DataFrame:
    state = _load_state(state_path)
    rows = []
    for key, payload in sorted(state["partitions"].items()):  # type: ignore[union-attr]
        rows.append({"partition_key": key, **payload})
    return pd.DataFrame(rows)


def corrupt_metric_partition(metric_dir: Path, state_path: Path, partition_key: str) -> Path:
    state = _load_state(state_path)
    if partition_key not in state["partitions"]:  # type: ignore[operator]
        raise KeyError(partition_key)
    target = metric_dir / f"{partition_key}.parquet"
    if not target.exists():
        raise FileNotFoundError(target)
    with target.open("ab") as handle:
        handle.write(b"\nV037_CORRUPTION_SENTINEL\n")
    return target


def output_hashes(metric_dir: Path) -> dict[str, str]:
    return {path.stem: sha256_file(path) for path in sorted(metric_dir.glob("*.parquet"))}
