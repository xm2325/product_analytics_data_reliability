from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from hashlib import sha256
from pathlib import Path
import json

import duckdb
import pandas as pd

from product_analytics.consumer_contract_evolution import (
    DEFAULT_RESPONSE_SCHEMA_VERSION,
    LATEST_RESPONSE_SCHEMA_VERSION,
    SUPPORTED_RESPONSE_SCHEMA_VERSIONS,
    contract_metadata,
    get_response_schema,
    validate_response_shape,
)


REPORTING_VERSION = "0.39.0"
REPORTING_SCHEMA_VERSION = DEFAULT_RESPONSE_SCHEMA_VERSION
MAX_QUERY_DAYS = 366


class ReportingContractError(ValueError):
    """Raised when a consumer request or backing materialisation violates the reporting contract."""


@dataclass(frozen=True)
class MetricSpec:
    name: str
    dtype: str
    unit: str
    description: str


METRIC_SPECS: tuple[MetricSpec, ...] = (
    MetricSpec("revenue_gbp", "float", "GBP", "Purchase-line revenue after the declared source-quality filters."),
    MetricSpec("orders", "integer", "orders", "Distinct purchase invoices."),
    MetricSpec("units", "float", "units", "Purchased units; fractional values are retained if present upstream."),
    MetricSpec("purchase_lines", "integer", "lines", "Count of purchase line items."),
    MetricSpec("active_customers", "integer", "customers", "Distinct identifiable customers with a purchase on the date."),
)
METRIC_BY_NAME = {spec.name: spec for spec in METRIC_SPECS}


@dataclass(frozen=True)
class MetricQuery:
    start_date: date
    end_date: date
    metrics: tuple[str, ...]


@dataclass(frozen=True)
class QueryWork:
    partitions_selected: int
    partition_keys: tuple[str, ...]
    metric_files_hashed: int
    rows_returned: int


def sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _month_keys_between(start_date: date, end_date: date) -> tuple[str, ...]:
    cursor = pd.Timestamp(start_date).to_period("M")
    end = pd.Timestamp(end_date).to_period("M")
    keys: list[str] = []
    while cursor <= end:
        keys.append(str(cursor))
        cursor += 1
    return tuple(keys)


def metric_catalog() -> list[dict[str, str]]:
    return [
        {
            "name": spec.name,
            "dtype": spec.dtype,
            "unit": spec.unit,
            "description": spec.description,
        }
        for spec in METRIC_SPECS
    ]


def reporting_contract() -> dict[str, object]:
    return {
        "version": REPORTING_VERSION,
        "schema_version": REPORTING_SCHEMA_VERSION,
        "default_schema_version": DEFAULT_RESPONSE_SCHEMA_VERSION,
        "latest_schema_version": LATEST_RESPONSE_SCHEMA_VERSION,
        "supported_schema_versions": list(SUPPORTED_RESPONSE_SCHEMA_VERSIONS),
        "schema_negotiation_rule": (
            "existing consumers stay on schema 1.0 unless they explicitly request a newer supported schema"
        ),
        "dataset": "UCI Online Retail II",
        "grain": "one row per calendar date",
        "partition_key": "calendar month of invoice/event date",
        "max_query_days": MAX_QUERY_DAYS,
        "missing_day_policy": "return an explicit zero row for dates with no materialised purchase activity",
        "metric_allowlist": [spec.name for spec in METRIC_SPECS],
        "integrity_rule": "before serving a query, selected metric partitions are SHA-verified and their source SHA/row-count bindings must agree with the pinned canonical manifest and durable incremental state",
        "partition_pruning_rule": "only month partitions intersecting the requested date window are read for metric values",
        "consumer_boundary": "the interface exposes historical event-date metrics only; the source has no ingestion timestamp, so it does not claim point-in-time/as-of reconstruction",
        "wall_clock_boundary": "shared-runner latency is diagnostic only; deterministic partition selection and response parity are the stable evidence",
    }


class RetailMetricStore:
    """Versioned, integrity-checked query interface over v0.37 metric partitions.

    The store deliberately stays framework-free. It is the reusable data-product
    boundary; a network transport can be added later without changing metric
    semantics or the response contract.
    """

    def __init__(
        self,
        metric_dir: Path,
        state_path: Path,
        source_manifest_path: Path,
    ) -> None:
        self.metric_dir = Path(metric_dir)
        self.state_path = Path(state_path)
        self.source_manifest_path = Path(source_manifest_path)
        if not self.metric_dir.is_dir():
            raise FileNotFoundError(self.metric_dir)
        if not self.state_path.is_file():
            raise FileNotFoundError(self.state_path)
        if not self.source_manifest_path.is_file():
            raise FileNotFoundError(self.source_manifest_path)

        self.source_manifest = pd.read_csv(self.source_manifest_path)
        required = {"partition_key", "path", "rows", "bytes", "sha256"}
        missing = required - set(self.source_manifest.columns)
        if missing:
            raise ReportingContractError(f"source manifest missing columns: {sorted(missing)}")
        if self.source_manifest["partition_key"].duplicated().any():
            raise ReportingContractError("source manifest has duplicate partition keys")
        self.source_manifest["partition_key"] = self.source_manifest["partition_key"].astype(str)
        self._source_by_key = {
            str(row["partition_key"]): row for row in self.source_manifest.to_dict("records")
        }

        state = json.loads(self.state_path.read_text(encoding="utf-8"))
        partitions = state.get("partitions")
        if not isinstance(partitions, dict):
            raise ReportingContractError("incremental state is missing its partitions mapping")
        self._state_by_key: dict[str, dict[str, object]] = {
            str(key): value for key, value in partitions.items() if isinstance(value, dict)
        }

        source_keys = set(self._source_by_key)
        state_keys = set(self._state_by_key)
        file_keys = {path.stem for path in self.metric_dir.glob("*.parquet")}
        if source_keys != state_keys or state_keys != file_keys:
            raise ReportingContractError(
                "reporting store partition set mismatch between source manifest, durable state and metric files"
            )
        if not source_keys:
            raise ReportingContractError("reporting store has no partitions")

        self.partition_keys = tuple(sorted(source_keys))
        first_key = self.partition_keys[0]
        last_key = self.partition_keys[-1]
        self._validate_selected_partition(first_key)
        if last_key != first_key:
            self._validate_selected_partition(last_key)
        self._con = duckdb.connect()
        first_path = self._metric_path(first_key)
        last_path = self._metric_path(last_key)
        bounds = self._con.execute(
            "SELECT MIN(date), MAX(date) FROM read_parquet(?)",
            [[str(first_path), str(last_path)]],
        ).fetchone()
        if not bounds or bounds[0] is None or bounds[1] is None:
            raise ReportingContractError("could not determine reporting-store date bounds")
        self.available_start = pd.Timestamp(bounds[0]).date()
        self.available_end = pd.Timestamp(bounds[1]).date()
        self.initialisation_boundary_partitions_read = 2 if first_path != last_path else 1

    def close(self) -> None:
        self._con.close()

    def __enter__(self) -> "RetailMetricStore":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def _metric_path(self, key: str) -> Path:
        state_row = self._state_by_key.get(key)
        if state_row is None:
            raise ReportingContractError(f"partition {key} is absent from durable state")
        metric_name = state_row.get("metric_path")
        if not isinstance(metric_name, str) or not metric_name:
            raise ReportingContractError(f"partition {key} has no metric_path in durable state")
        return self.metric_dir / metric_name

    def _validate_selected_partition(self, key: str) -> dict[str, str]:
        source = self._source_by_key[key]
        state = self._state_by_key[key]
        if state.get("status") != "complete":
            raise ReportingContractError(f"partition {key} is not complete")
        if str(state.get("source_sha256")) != str(source["sha256"]):
            raise ReportingContractError(f"partition {key} source SHA binding does not match manifest")
        if int(state.get("source_rows", -1)) != int(source["rows"]):
            raise ReportingContractError(f"partition {key} source row binding does not match manifest")
        metric_path = self._metric_path(key)
        if not metric_path.is_file():
            raise ReportingContractError(f"partition {key} metric file is missing")
        expected_metric_sha = str(state.get("metric_sha256"))
        observed_metric_sha = sha256_file(metric_path)
        if observed_metric_sha != expected_metric_sha:
            raise ReportingContractError(f"partition {key} metric SHA does not match durable state")
        return {
            "partition_key": key,
            "source_sha256": str(source["sha256"]),
            "metric_sha256": observed_metric_sha,
        }

    def _validate_query(self, query: MetricQuery) -> None:
        if query.start_date > query.end_date:
            raise ReportingContractError("start_date must be on or before end_date")
        days = (query.end_date - query.start_date).days + 1
        if days > MAX_QUERY_DAYS:
            raise ReportingContractError(
                f"query spans {days} days; maximum allowed window is {MAX_QUERY_DAYS}"
            )
        if query.start_date < self.available_start or query.end_date > self.available_end:
            raise ReportingContractError(
                f"query window must stay within available data {self.available_start}..{self.available_end}"
            )
        if not query.metrics:
            raise ReportingContractError("at least one metric is required")
        if len(set(query.metrics)) != len(query.metrics):
            raise ReportingContractError("metric names must be unique")
        unknown = [name for name in query.metrics if name not in METRIC_BY_NAME]
        if unknown:
            raise ReportingContractError(f"unknown metric(s): {unknown}")

    @staticmethod
    def _validate_schema_version(schema_version: str) -> None:
        try:
            get_response_schema(schema_version)
        except ValueError as exc:
            raise ReportingContractError(str(exc)) from exc

    def query(
        self,
        query: MetricQuery,
        *,
        schema_version: str = DEFAULT_RESPONSE_SCHEMA_VERSION,
    ) -> tuple[dict[str, object], QueryWork]:
        self._validate_schema_version(schema_version)
        self._validate_query(query)
        requested_keys = _month_keys_between(query.start_date, query.end_date)
        unavailable = [key for key in requested_keys if key not in self._state_by_key]
        if unavailable:
            raise ReportingContractError(f"requested date range crosses unavailable partition(s): {unavailable}")

        provenance = [self._validate_selected_partition(key) for key in requested_keys]
        paths = [str(self._metric_path(key)) for key in requested_keys]
        metric_names = list(query.metrics)
        metric_projection = ", ".join(metric_names)
        coalesced = ", ".join(f"COALESCE(m.{name}, 0) AS {name}" for name in metric_names)
        sql = f"""
            WITH metric_rows AS (
                SELECT date, {metric_projection}
                FROM read_parquet(?)
                WHERE date BETWEEN CAST(? AS DATE) AND CAST(? AS DATE)
            ), dates AS (
                SELECT CAST(value AS DATE) AS date
                FROM generate_series(CAST(? AS DATE), CAST(? AS DATE), INTERVAL 1 DAY) AS t(value)
            )
            SELECT d.date, {coalesced}
            FROM dates d
            LEFT JOIN metric_rows m USING (date)
            ORDER BY d.date
        """
        frame = self._con.execute(
            sql,
            [
                paths,
                query.start_date.isoformat(),
                query.end_date.isoformat(),
                query.start_date.isoformat(),
                query.end_date.isoformat(),
            ],
        ).df()

        records: list[dict[str, object]] = []
        for row in frame.to_dict("records"):
            record: dict[str, object] = {"date": pd.Timestamp(row["date"]).date().isoformat()}
            for name in metric_names:
                value = row[name]
                spec = METRIC_BY_NAME[name]
                record[name] = int(value) if spec.dtype == "integer" else float(value)
            records.append(record)

        query_payload = {
            "start_date": query.start_date.isoformat(),
            "end_date": query.end_date.isoformat(),
            "metrics": metric_names,
        }
        digest_payload = json.dumps(
            {"query": query_payload, "data": records}, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        response_hash = sha256(digest_payload).hexdigest()
        response: dict[str, object] = {
            "schema_version": schema_version,
            "data_product_version": REPORTING_VERSION,
            "dataset": "UCI Online Retail II",
            "query": query_payload,
            "availability": {
                "start_date": self.available_start.isoformat(),
                "end_date": self.available_end.isoformat(),
                "no_ingestion_time_claim": True,
            },
            "partition_provenance": provenance,
            "row_count": len(records),
            "response_sha256": response_hash,
            "data": records,
        }
        if schema_version == LATEST_RESPONSE_SCHEMA_VERSION:
            response["contract"] = contract_metadata(metric_catalog())
        try:
            validate_response_shape(
                response,
                schema_version=schema_version,
                requested_metrics=query.metrics,
                strict_top_level=True,
            )
        except ValueError as exc:
            raise ReportingContractError(
                f"generated response violates schema {schema_version}: {exc}"
            ) from exc

        work = QueryWork(
            partitions_selected=len(requested_keys),
            partition_keys=requested_keys,
            metric_files_hashed=len(requested_keys),
            rows_returned=len(records),
        )
        return response, work
