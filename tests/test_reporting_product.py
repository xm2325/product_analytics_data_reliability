from __future__ import annotations

from datetime import date
from pathlib import Path
import json

import duckdb
import pandas as pd
import pytest

from product_analytics.consumer_contract_evolution import (
    DEFAULT_RESPONSE_SCHEMA_VERSION,
    LATEST_RESPONSE_SCHEMA_VERSION,
)
from product_analytics.reporting_product import (
    MAX_QUERY_DAYS,
    MetricQuery,
    ReportingContractError,
    RetailMetricStore,
    sha256_file,
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
    source_rows = []
    state = {"version": "0.37.0", "partitions": {}}
    for key, path, rows in [("2011-01", jan, 100), ("2011-02", feb, 200)]:
        source_sha = ("a" if key == "2011-01" else "b") * 64
        source_rows.append(
            {
                "partition_key": key,
                "path": f"source-{key}.parquet",
                "rows": rows,
                "bytes": 123,
                "sha256": source_sha,
            }
        )
        state["partitions"][key] = {
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


def test_query_prunes_to_one_month_and_zero_fills_missing_days(tmp_path: Path) -> None:
    metric_dir, state, manifest = _fixture(tmp_path)
    with RetailMetricStore(metric_dir, state, manifest) as store:
        response, work = store.query(
            MetricQuery(date(2011, 2, 1), date(2011, 2, 3), ("orders", "revenue_gbp"))
        )
    assert work.partition_keys == ("2011-02",)
    assert work.metric_files_hashed == 1
    assert response["row_count"] == 3
    assert response["data"][1] == {
        "date": "2011-02-02",
        "orders": 0,
        "revenue_gbp": 0.0,
    }


def test_cross_month_query_reads_exactly_two_partitions(tmp_path: Path) -> None:
    metric_dir, state, manifest = _fixture(tmp_path)
    with RetailMetricStore(metric_dir, state, manifest) as store:
        response, work = store.query(
            MetricQuery(date(2011, 1, 31), date(2011, 2, 1), ("active_customers",))
        )
    assert work.partition_keys == ("2011-01", "2011-02")
    assert response["row_count"] == 2
    assert [row["active_customers"] for row in response["data"]] == [2, 3]


def test_unknown_metric_and_invalid_ranges_are_rejected(tmp_path: Path) -> None:
    metric_dir, state, manifest = _fixture(tmp_path)
    with RetailMetricStore(metric_dir, state, manifest) as store:
        with pytest.raises(ReportingContractError, match="unknown metric"):
            store.query(MetricQuery(date(2011, 2, 1), date(2011, 2, 1), ("profit",)))
        with pytest.raises(ReportingContractError, match="available data"):
            store.query(MetricQuery(date(2011, 1, 29), date(2011, 2, 1), ("orders",)))
        with pytest.raises(ReportingContractError, match="start_date"):
            store.query(MetricQuery(date(2011, 2, 2), date(2011, 2, 1), ("orders",)))


def test_query_width_limit_is_contractual(tmp_path: Path) -> None:
    metric_dir, state, manifest = _fixture(tmp_path)
    with RetailMetricStore(metric_dir, state, manifest) as store:
        store.available_start = date(2010, 1, 1)
        store.available_end = date(2012, 1, 1)
        with pytest.raises(ReportingContractError, match=str(MAX_QUERY_DAYS)):
            store.query(MetricQuery(date(2010, 1, 1), date(2011, 1, 2), ("orders",)))


def test_boundary_partition_tampering_is_rejected_before_duckdb_read(tmp_path: Path) -> None:
    metric_dir, state, manifest = _fixture(tmp_path)
    target = metric_dir / "2011-02.parquet"
    with target.open("ab") as handle:
        handle.write(b"tamper")
    with pytest.raises(ReportingContractError, match="metric SHA"):
        RetailMetricStore(metric_dir, state, manifest)


def test_schema_1_0_remains_default_and_1_1_is_explicit_opt_in(tmp_path: Path) -> None:
    metric_dir, state, manifest = _fixture(tmp_path)
    query = MetricQuery(date(2011, 2, 1), date(2011, 2, 3), ("orders", "revenue_gbp"))
    with RetailMetricStore(metric_dir, state, manifest) as store:
        v1_0, work_1_0 = store.query(query)
        v1_1, work_1_1 = store.query(query, schema_version=LATEST_RESPONSE_SCHEMA_VERSION)

    assert v1_0["schema_version"] == DEFAULT_RESPONSE_SCHEMA_VERSION == "1.0"
    assert "contract" not in v1_0
    assert v1_1["schema_version"] == LATEST_RESPONSE_SCHEMA_VERSION == "1.1"
    assert v1_1["contract"]["backward_compatible_via_negotiation"] == ["1.0"]
    assert v1_0["query"] == v1_1["query"]
    assert v1_0["data"] == v1_1["data"]
    assert v1_0["response_sha256"] == v1_1["response_sha256"]
    assert work_1_0 == work_1_1


def test_unsupported_schema_version_is_rejected_before_query_execution(tmp_path: Path) -> None:
    metric_dir, state, manifest = _fixture(tmp_path)
    with RetailMetricStore(metric_dir, state, manifest) as store:
        with pytest.raises(ReportingContractError, match="unsupported reporting schema"):
            store.query(
                MetricQuery(date(2011, 2, 1), date(2011, 2, 1), ("orders",)),
                schema_version="2.0",
            )
