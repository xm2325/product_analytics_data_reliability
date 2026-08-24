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
    source_hashes_computed: int


class SimulatedInterruption(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sql_literal(path: Path) -> str:
    return "'" + path.as_posix().replace("'", "''") + "'"


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
    """Canonicalise an external snapshot into immutable month-partitioned Parquet."""
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
                "COPY (SELECT * FROM partition_frame ORDER BY source_row_id) TO "
                f"{_sql_literal(target)} (FORMAT PARQUET, COMPRESSION ZSTD)"
            )
            con.unregister("partition_frame")
            rows.append(
                {
                    "partition_key": key,
                    "path": target.name,
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


def verify_source_manifest(source_dir: Path, source_manifest: pd.DataFrame) -> None:
    """Expensive integrity audit: hash every canonical source partition."""
    expected = set(source_manifest["partition_key"].astype(str))
    observed = {path.stem for path in source_dir.glob("*.parquet")}
    if expected != observed:
        raise AssertionError(f"Source partition set mismatch: expected={expected}, observed={observed}")
    for row in source_manifest.to_dict("records"):
        path = source_dir / str(row["path"])
        if path.stat().st_size != int(row["bytes"]):
            raise AssertionError(f"Source partition size mismatch: {path.name}")
        if sha256_file(path) != str(row["sha256"]):
            raise AssertionError(f"Source partition SHA mismatch: {path.name}")


def _aggregate_partition(
    con: duckdb.DuckDBPyConnection,
    source_path: Path,
    output_path: Path,
) -> None:
    """Aggregate one source partition with a single Parquet scan.

    The expected row count is already certified by the immutable source
    manifest, so a second COUNT(*) scan would add I/O without adding evidence.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    source_sql = _sql_literal(source_path)
    output_sql = _sql_literal(output_path)
    con.execute(
        f"""
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
            FROM read_parquet({source_sql})
            WHERE invoice_ts IS NOT NULL
            GROUP BY 1
            ORDER BY 1
        ) TO {output_sql} (FORMAT PARQUET, COMPRESSION ZSTD)
        """
    )


def run_incremental(
    source_dir: Path,
    source_manifest: pd.DataFrame,
    metric_dir: Path,
    state_path: Path,
    *,
    stop_after_processed: int | None = None,
    verify_source_hashes: bool = False,
) -> IncrementalRunStats:
    """Process only missing, source-revised or output-invalidated month partitions.

    Normal runs trust the immutable canonical source manifest and only stat the
    large source Parquet files. `verify_source_hashes=True` is an explicit,
    expensive integrity audit. Small derived outputs are hashed on every reuse
    check so stale/corrupt materialisations cannot be silently accepted.

    When work is required, all partitions in the run share one DuckDB
    connection and each changed partition is scanned only once for aggregation.
    """
    started = perf_counter()
    state = _load_state(state_path)
    partitions: dict[str, dict[str, object]] = state["partitions"]  # type: ignore[assignment]
    processed = skipped = rows_scanned = source_hashes_computed = 0
    con: duckdb.DuckDBPyConnection | None = None

    required_columns = {"partition_key", "path", "rows", "bytes", "sha256"}
    missing = required_columns - set(source_manifest.columns)
    if missing:
        raise ValueError(f"Source manifest missing columns: {sorted(missing)}")

    try:
        for row in source_manifest.sort_values("partition_key").to_dict("records"):
            key = str(row["partition_key"])
            source_path = source_dir / str(row["path"])
            if not source_path.exists():
                raise FileNotFoundError(source_path)
            if source_path.stat().st_size != int(row["bytes"]):
                raise RuntimeError(f"Canonical source partition size changed: {source_path.name}")
            expected_source_sha = str(row["sha256"])
            if verify_source_hashes:
                source_hashes_computed += 1
                if sha256_file(source_path) != expected_source_sha:
                    raise RuntimeError(f"Canonical source partition SHA changed: {source_path.name}")

            metric_path = metric_dir / f"{key}.parquet"
            previous = partitions.get(key)
            reusable = bool(
                previous
                and previous.get("source_sha256") == expected_source_sha
                and previous.get("source_rows") == int(row["rows"])
                and metric_path.exists()
                and previous.get("metric_sha256") == sha256_file(metric_path)
                and previous.get("status") == "complete"
            )
            if reusable:
                skipped += 1
                continue

            if con is None:
                con = duckdb.connect()
            _aggregate_partition(con, source_path, metric_path)
            rows_scanned_now = int(row["rows"])
            rows_scanned += rows_scanned_now
            processed += 1
            partitions[key] = {
                "status": "complete",
                "source_path": source_path.name,
                "source_rows": rows_scanned_now,
                "source_sha256": expected_source_sha,
                "metric_path": metric_path.name,
                "metric_sha256": sha256_file(metric_path),
            }
            state["partitions"] = partitions
            _write_json(state_path, state)

            if stop_after_processed is not None and processed >= stop_after_processed:
                raise SimulatedInterruption(
                    f"simulated interruption after {processed} newly processed partitions"
                )
    finally:
        if con is not None:
            con.close()

    return IncrementalRunStats(
        processed_partitions=processed,
        skipped_partitions=skipped,
        rows_scanned=rows_scanned,
        elapsed_seconds=perf_counter() - started,
        source_hashes_computed=source_hashes_computed,
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
