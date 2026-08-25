from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from datetime import date
from hashlib import sha256
import json

from product_analytics.consumer_contract_evolution import DEFAULT_RESPONSE_SCHEMA_VERSION
from product_analytics.reporting_product import MetricQuery, ReportingContractError, RetailMetricStore


WORKLOAD_VERSION = "0.40.0"
DEFAULT_MAX_WORKERS = 8


@dataclass(frozen=True)
class WorkloadRequest:
    request_id: str
    consumer_id: str
    query: MetricQuery
    schema_version: str = DEFAULT_RESPONSE_SCHEMA_VERSION
    expected_success: bool = True

    def to_dict(self) -> dict[str, object]:
        return {
            "request_id": self.request_id,
            "consumer_id": self.consumer_id,
            "schema_version": self.schema_version,
            "expected_success": self.expected_success,
            "query": {
                "start_date": self.query.start_date.isoformat(),
                "end_date": self.query.end_date.isoformat(),
                "metrics": list(self.query.metrics),
            },
        }


@dataclass(frozen=True)
class WorkloadResult:
    request_id: str
    consumer_id: str
    status: str
    schema_version: str
    response_sha256: str | None
    response_payload_sha256: str | None
    partitions_selected: int | None
    partition_keys: tuple[str, ...]
    metric_files_hashed: int | None
    rows_returned: int | None
    error_type: str | None

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["partition_keys"] = list(self.partition_keys)
        return payload


def reference_workload() -> tuple[WorkloadRequest, ...]:
    hot_query = MetricQuery(
        date(2010, 12, 1),
        date(2010, 12, 7),
        ("revenue_gbp", "orders", "units", "purchase_lines", "active_customers"),
    )
    requests = [
        WorkloadRequest(
            "finance-dec-v1-0",
            "finance",
            MetricQuery(date(2010, 12, 1), date(2010, 12, 31), ("revenue_gbp", "orders")),
            "1.0",
        ),
        WorkloadRequest(
            "finance-dec-v1-1",
            "finance-next",
            MetricQuery(date(2010, 12, 1), date(2010, 12, 31), ("revenue_gbp", "orders")),
            "1.1",
        ),
        WorkloadRequest(
            "growth-q1-2011",
            "growth",
            MetricQuery(date(2011, 1, 1), date(2011, 3, 31), ("orders", "active_customers")),
        ),
        WorkloadRequest(
            "operations-winter",
            "operations",
            MetricQuery(date(2010, 11, 15), date(2011, 1, 15), ("units", "purchase_lines")),
        ),
        WorkloadRequest(
            "planning-2010",
            "planning",
            MetricQuery(
                date(2010, 1, 1),
                date(2010, 12, 31),
                ("revenue_gbp", "orders", "units", "purchase_lines", "active_customers"),
            ),
            "1.1",
        ),
        WorkloadRequest(
            "early-history",
            "analyst",
            MetricQuery(date(2009, 12, 1), date(2009, 12, 31), ("revenue_gbp", "orders")),
        ),
    ]
    for index in range(1, 7):
        requests.append(
            WorkloadRequest(
                f"hot-dec-week-{index}",
                f"hot-consumer-{index}",
                hot_query,
                "1.1",
            )
        )
    return tuple(requests)


def failure_injection_workload() -> tuple[WorkloadRequest, ...]:
    return (
        WorkloadRequest(
            "bad-unknown-metric",
            "faulty-metric-client",
            MetricQuery(date(2010, 12, 1), date(2010, 12, 2), ("profit",)),
            expected_success=False,
        ),
        WorkloadRequest(
            "bad-unsupported-schema",
            "faulty-schema-client",
            MetricQuery(date(2010, 12, 1), date(2010, 12, 2), ("orders",)),
            schema_version="2.0",
            expected_success=False,
        ),
        WorkloadRequest(
            "bad-duplicate-metric",
            "faulty-duplicate-client",
            MetricQuery(date(2010, 12, 1), date(2010, 12, 2), ("orders", "orders")),
            expected_success=False,
        ),
    )


def _response_payload_sha(response: dict[str, object]) -> str:
    payload = json.dumps(response, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return sha256(payload).hexdigest()


def execute_request(store: RetailMetricStore, request: WorkloadRequest) -> WorkloadResult:
    try:
        response, work = store.query(request.query, schema_version=request.schema_version)
    except ReportingContractError as exc:
        return WorkloadResult(
            request_id=request.request_id,
            consumer_id=request.consumer_id,
            status="ERROR",
            schema_version=request.schema_version,
            response_sha256=None,
            response_payload_sha256=None,
            partitions_selected=None,
            partition_keys=(),
            metric_files_hashed=None,
            rows_returned=None,
            error_type=type(exc).__name__,
        )
    return WorkloadResult(
        request_id=request.request_id,
        consumer_id=request.consumer_id,
        status="SUCCESS",
        schema_version=request.schema_version,
        response_sha256=str(response["response_sha256"]),
        response_payload_sha256=_response_payload_sha(response),
        partitions_selected=work.partitions_selected,
        partition_keys=work.partition_keys,
        metric_files_hashed=work.metric_files_hashed,
        rows_returned=work.rows_returned,
        error_type=None,
    )


def execute_serial(store: RetailMetricStore, requests: tuple[WorkloadRequest, ...]) -> tuple[WorkloadResult, ...]:
    return tuple(execute_request(store, request) for request in requests)


def execute_concurrent(
    store: RetailMetricStore,
    requests: tuple[WorkloadRequest, ...],
    *,
    max_workers: int = DEFAULT_MAX_WORKERS,
) -> tuple[WorkloadResult, ...]:
    if max_workers < 1:
        raise ValueError("max_workers must be at least 1")
    by_id: dict[str, WorkloadResult] = {}
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(execute_request, store, request): request.request_id for request in requests}
        for future in as_completed(futures):
            result = future.result()
            by_id[result.request_id] = result
    return tuple(by_id[request.request_id] for request in requests)


def workload_digest(results: tuple[WorkloadResult, ...]) -> str:
    payload = [result.to_dict() for result in sorted(results, key=lambda row: row.request_id)]
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return sha256(encoded).hexdigest()
