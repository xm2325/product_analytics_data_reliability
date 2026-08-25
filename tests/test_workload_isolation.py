from __future__ import annotations

from datetime import date
from pathlib import Path
import json

import duckdb
import pandas as pd

from product_analytics.reporting_product import MetricQuery, RetailMetricStore, sha256_file
from product_analytics.workload_isolation import (
    WorkloadRequest,
    execute_concurrent,
    execute_serial,
    workload_digest,
)


def _write_partition(path: Path, rows: list[dict[str, object]]) -> None:
    frame = pd.DataFrame(rows)
    con = duckdb.connect()
    try:
        con.register("frame", frame)
        literal = "'" + path.as_posix().replace("'", "''") + "'"
        con.execute(f"COPY (SELECT * FROM frame) TO {literal} (FORMAT PARQUET, COMPRESSION ZSTD)")
    finally:
        con.close()


def _fixture(tmp_path: Path) -> tuple[Path, Path, Path]:
    metric_dir = tmp_path / "metrics"
    metric_dir.mkdir()
    jan = metric_dir / "2011-01.parquet"
    feb = metric_dir / "2011-02.parquet"
    columns = ("revenue_gbp", "orders", "units", "purchase_lines", "active_customers")
    _write_partition(
        jan,
        [
            {"date": date(2011, 1, 30), "revenue_gbp": 10.0, "orders": 1, "units": 2.0, "purchase_lines": 1, "active_customers": 1},
            {"date": date(2011, 1, 31), "revenue_gbp": 20.0, "orders": 2, "units": 3.0, "purchase_lines": 2, "active_customers": 2},
        ],
    )
    _write_partition(
        feb,
        [
            {"date": date(2011, 2, 1), "revenue_gbp": 30.0, "orders": 3, "units": 4.0, "purchase_lines": 3, "active_customers": 3},
            {"date": date(2011, 2, 3), "revenue_gbp": 40.0, "orders": 4, "units": 5.0, "purchase_lines": 4, "active_customers": 4},
        ],
    )
    source_rows: list[dict[str, object]] = []
    state: dict[str, object] = {"version": "0.37.0", "partitions": {}}
    partitions = state["partitions"]
    assert isinstance(partitions, dict)
    for key, path, rows in (("2011-01", jan, 100), ("2011-02", feb, 200)):
        source_sha = ("a" if key == "2011-01" else "b") * 64
        source_rows.append({"partition_key": key, "path": f"source-{key}.parquet", "rows": rows, "bytes": 123, "sha256": source_sha})
        partitions[key] = {
            "status": "complete",
            "source_path": f"source-{key}.parquet",
            "source_rows": rows,
            "source_sha256": source_sha,
            "metric_path": path.name,
            "metric_sha256": sha256_file(path),
        }
    manifest = tmp_path / "source_manifest.csv"
    pd.DataFrame(source_rows).to_csv(manifest, index=False)
    state_path = tmp_path / "state.json"
    state_path.write_text(json.dumps(state), encoding="utf-8")
    return metric_dir, state_path, manifest


def test_shared_store_concurrent_replay_matches_serial_exactly(tmp_path: Path) -> None:
    metric_dir, state, manifest = _fixture(tmp_path)
    requests = (
        WorkloadRequest("jan", "finance", MetricQuery(date(2011, 1, 30), date(2011, 1, 31), ("orders", "revenue_gbp"))),
        WorkloadRequest("cross", "growth", MetricQuery(date(2011, 1, 31), date(2011, 2, 3), ("active_customers",)), "1.1"),
        WorkloadRequest("hot-1", "consumer-a", MetricQuery(date(2011, 2, 1), date(2011, 2, 3), ("orders",)), "1.1"),
        WorkloadRequest("hot-2", "consumer-b", MetricQuery(date(2011, 2, 1), date(2011, 2, 3), ("orders",)), "1.1"),
    )
    with RetailMetricStore(metric_dir, state, manifest) as store:
        serial = execute_serial(store, requests)
        concurrent = execute_concurrent(store, requests, max_workers=4)
    assert concurrent == serial
    assert workload_digest(concurrent) == workload_digest(serial)
    assert concurrent[2].response_payload_sha256 == concurrent[3].response_payload_sha256


def test_failed_consumers_do_not_change_successful_results(tmp_path: Path) -> None:
    metric_dir, state, manifest = _fixture(tmp_path)
    valid = WorkloadRequest(
        "valid",
        "healthy-client",
        MetricQuery(date(2011, 2, 1), date(2011, 2, 3), ("orders", "active_customers")),
        "1.1",
    )
    mixed = (
        valid,
        WorkloadRequest("bad-metric", "bad-a", MetricQuery(date(2011, 2, 1), date(2011, 2, 2), ("profit",)), expected_success=False),
        WorkloadRequest("bad-schema", "bad-b", MetricQuery(date(2011, 2, 1), date(2011, 2, 2), ("orders",)), "2.0", False),
        WorkloadRequest("bad-duplicate", "bad-c", MetricQuery(date(2011, 2, 1), date(2011, 2, 2), ("orders", "orders")), expected_success=False),
    )
    with RetailMetricStore(metric_dir, state, manifest) as store:
        baseline = execute_serial(store, (valid,))[0]
        outcomes = execute_concurrent(store, mixed, max_workers=4)
        after = execute_serial(store, (valid,))[0]

    by_id = {result.request_id: result for result in outcomes}
    assert by_id["valid"] == baseline == after
    assert {by_id[key].status for key in ("bad-metric", "bad-schema", "bad-duplicate")} == {"ERROR"}
    assert {by_id[key].error_type for key in ("bad-metric", "bad-schema", "bad-duplicate")} == {"ReportingContractError"}
