from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from hashlib import sha256
from pathlib import Path
import json

import pandas as pd

from product_analytics.reporting_product import MetricQuery, ReportingContractError, RetailMetricStore


INTEGER_METRICS = {"orders", "purchase_lines", "active_customers"}


def _payload_sha(response: dict[str, object]) -> str:
    payload = json.dumps(response, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return sha256(payload).hexdigest()


def _compact_result(store: RetailMetricStore, request: dict[str, object]) -> dict[str, object]:
    query_payload = request["query"]
    assert isinstance(query_payload, dict)
    query = MetricQuery(
        date.fromisoformat(str(query_payload["start_date"])),
        date.fromisoformat(str(query_payload["end_date"])),
        tuple(str(value) for value in query_payload["metrics"]),
    )
    schema_version = str(request["schema_version"])
    try:
        response, work = store.query(query, schema_version=schema_version)
    except ReportingContractError as exc:
        return {
            "request_id": str(request["request_id"]),
            "consumer_id": str(request["consumer_id"]),
            "status": "ERROR",
            "schema_version": schema_version,
            "response_sha256": None,
            "response_payload_sha256": None,
            "partitions_selected": None,
            "partition_keys": [],
            "metric_files_hashed": None,
            "rows_returned": None,
            "error_type": type(exc).__name__,
        }
    return {
        "request_id": str(request["request_id"]),
        "consumer_id": str(request["consumer_id"]),
        "status": "SUCCESS",
        "schema_version": schema_version,
        "response_sha256": str(response["response_sha256"]),
        "response_payload_sha256": _payload_sha(response),
        "partitions_selected": work.partitions_selected,
        "partition_keys": list(work.partition_keys),
        "metric_files_hashed": work.metric_files_hashed,
        "rows_returned": work.rows_returned,
        "error_type": None,
        "_response": response,
    }


def _public(result: dict[str, object]) -> dict[str, object]:
    return {key: value for key, value in result.items() if key != "_response"}


def _expected_rows(daily: pd.DataFrame, request: dict[str, object]) -> list[dict[str, object]]:
    query = request["query"]
    assert isinstance(query, dict)
    start = date.fromisoformat(str(query["start_date"]))
    end = date.fromisoformat(str(query["end_date"]))
    metrics = [str(value) for value in query["metrics"]]
    frame = daily.copy()
    frame["date"] = pd.to_datetime(frame["date"]).dt.date
    frame = frame.loc[(frame["date"] >= start) & (frame["date"] <= end), ["date", *metrics]]
    rows: list[dict[str, object]] = []
    for row in frame.to_dict("records"):
        out: dict[str, object] = {"date": row["date"].isoformat()}
        for metric in metrics:
            out[metric] = int(row[metric]) if metric in INTEGER_METRICS else float(row[metric])
        rows.append(out)
    return rows


def _run_concurrent(store: RetailMetricStore, requests: list[dict[str, object]], max_workers: int) -> list[dict[str, object]]:
    by_id: dict[str, dict[str, object]] = {}
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(_compact_result, store, request): str(request["request_id"]) for request in requests}
        for future in as_completed(futures):
            result = future.result()
            by_id[str(result["request_id"])] = result
    return [by_id[str(request["request_id"])] for request in requests]


def main() -> None:
    parser = argparse.ArgumentParser(description="Independently validate v0.40 multi-consumer workload isolation")
    parser.add_argument("incremental_dir", type=Path)
    args = parser.parse_args()
    root = args.incremental_dir

    requests = json.loads((root / "workload_isolation_requests.json").read_text(encoding="utf-8"))
    serial_reference = json.loads((root / "workload_isolation_serial_results.json").read_text(encoding="utf-8"))
    concurrent_reference = json.loads((root / "workload_isolation_concurrent_results.json").read_text(encoding="utf-8"))
    mixed_reference = json.loads((root / "workload_isolation_mixed_results.json").read_text(encoding="utf-8"))
    evidence = json.loads((root / "workload_isolation_evidence.json").read_text(encoding="utf-8"))
    daily = pd.read_csv(root / "incremental_daily_metrics.csv")

    valid_requests = [request for request in requests if bool(request["expected_success"])]
    failed_requests = [request for request in requests if not bool(request["expected_success"])]
    max_workers = int(evidence["max_workers"])

    metric_dir = root / "metric_partitions"
    state_path = root / "incremental_state.json"
    manifest_path = root / "incremental_source_partition_manifest.csv"
    with RetailMetricStore(metric_dir, state_path, manifest_path) as store:
        serial = [_compact_result(store, request) for request in valid_requests]
        concurrent = _run_concurrent(store, valid_requests, max_workers)
        mixed = _run_concurrent(store, requests, max_workers)
        post_failure = [_compact_result(store, request) for request in valid_requests]

    serial_public = [_public(result) for result in serial]
    concurrent_public = [_public(result) for result in concurrent]
    mixed_public = [_public(result) for result in mixed]
    post_failure_public = [_public(result) for result in post_failure]

    if serial_public != serial_reference:
        raise AssertionError("Independent serial replay differs from generated workload baseline")
    if concurrent_public != concurrent_reference or concurrent_public != serial_public:
        raise AssertionError("Independent concurrent replay differs from serial/generated evidence")
    if mixed_public != mixed_reference:
        raise AssertionError("Independent mixed replay differs from generated evidence")
    if post_failure_public != serial_public:
        raise AssertionError("Healthy results changed after failure-injection replay")

    for request, result in zip(valid_requests, serial):
        response = result["_response"]
        assert isinstance(response, dict)
        expected = _expected_rows(daily, request)
        if response["data"] != expected:
            raise AssertionError(f"{request['request_id']} does not independently reconcile to daily metrics")
        digest_payload = json.dumps(
            {"query": response["query"], "data": response["data"]},
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        if response["response_sha256"] != sha256(digest_payload).hexdigest():
            raise AssertionError(f"{request['request_id']} response SHA does not independently recompute")

    mixed_by_id = {str(result["request_id"]): result for result in mixed_public}
    failed_ids = {str(request["request_id"]) for request in failed_requests}
    observed_failed_ids = {request_id for request_id, result in mixed_by_id.items() if result["status"] == "ERROR"}
    if observed_failed_ids != failed_ids:
        raise AssertionError(f"Failure isolation mismatch: expected={failed_ids}, observed={observed_failed_ids}")
    if any(mixed_by_id[request_id]["error_type"] != "ReportingContractError" for request_id in failed_ids):
        raise AssertionError("Injected failures did not fail through ReportingContractError")

    serial_by_id = {str(result["request_id"]): result for result in serial_public}
    for request in valid_requests:
        request_id = str(request["request_id"])
        if mixed_by_id[request_id] != serial_by_id[request_id]:
            raise AssertionError(f"Healthy request {request_id} changed in mixed workload")

    hot_hashes = {
        result["response_payload_sha256"]
        for result in serial_public
        if str(result["request_id"]).startswith("hot-dec-week-")
    }
    total_partitions = sum(int(result["partitions_selected"]) for result in serial_public)
    total_files = sum(int(result["metric_files_hashed"]) for result in serial_public)
    total_rows = sum(int(result["rows_returned"]) for result in serial_public)
    unique_partitions = {key for result in serial_public for key in result["partition_keys"]}

    expected_evidence = {
        "version": "0.40.0",
        "valid_requests": len(valid_requests),
        "valid_consumers": len({str(request["consumer_id"]) for request in valid_requests}),
        "serial_concurrent_exact_result_parity": True,
        "serial_concurrent_workload_digest_parity": True,
        "aggregate_metric_partitions_selected": total_partitions,
        "aggregate_metric_files_hashed": total_files,
        "aggregate_rows_returned": total_rows,
        "unique_metric_partitions_touched": len(unique_partitions),
        "hot_partition_parallel_consumers": len([request for request in valid_requests if str(request["request_id"]).startswith("hot-dec-week-")]),
        "hot_partition_unique_payload_hashes": len(hot_hashes),
        "mixed_workload_requests": len(requests),
        "injected_failure_requests": len(failed_requests),
        "isolated_reporting_contract_failures": len(observed_failed_ids),
        "healthy_results_preserved_in_mixed_workload": True,
        "healthy_results_preserved_after_failures": True,
        "wall_clock_gate": False,
    }
    for key, expected in expected_evidence.items():
        if evidence.get(key) != expected:
            raise AssertionError(f"Evidence field {key}: generated={evidence.get(key)!r}, independent={expected!r}")

    if "seconds" in json.dumps(evidence).lower() or "qps" in json.dumps(evidence).lower() and bool(evidence.get("wall_clock_gate")):
        raise AssertionError("Workload evidence must not certify shared-runner wall-clock throughput")

    print(
        "Workload-isolation validation passed: "
        f"valid={len(valid_requests)}, mixed={len(requests)}, failures={len(failed_requests)}, "
        f"workers={max_workers}, partitions={total_partitions}, rows={total_rows}"
    )


if __name__ == "__main__":
    main()
