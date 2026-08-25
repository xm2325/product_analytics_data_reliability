from __future__ import annotations

import argparse
from pathlib import Path
import json

from product_analytics.reporting_product import RetailMetricStore
from product_analytics.workload_isolation import (
    DEFAULT_MAX_WORKERS,
    WORKLOAD_VERSION,
    execute_concurrent,
    execute_serial,
    failure_injection_workload,
    reference_workload,
    workload_digest,
)


def _write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build v0.40 deterministic multi-consumer workload-isolation evidence"
    )
    parser.add_argument(
        "--incremental-dir",
        type=Path,
        default=Path("build/incremental-retail"),
    )
    args = parser.parse_args()
    root = args.incremental_dir
    metric_dir = root / "metric_partitions"
    state_path = root / "incremental_state.json"
    source_manifest_path = root / "incremental_source_partition_manifest.csv"
    for required in (metric_dir, state_path, source_manifest_path):
        if not required.exists():
            raise FileNotFoundError(required)

    valid_requests = reference_workload()
    failure_requests = failure_injection_workload()
    mixed_requests = valid_requests + failure_requests

    with RetailMetricStore(metric_dir, state_path, source_manifest_path) as store:
        serial = execute_serial(store, valid_requests)
        concurrent = execute_concurrent(
            store,
            valid_requests,
            max_workers=DEFAULT_MAX_WORKERS,
        )
        mixed = execute_concurrent(
            store,
            mixed_requests,
            max_workers=DEFAULT_MAX_WORKERS,
        )
        post_failure = execute_serial(store, valid_requests)

    if any(result.status != "SUCCESS" for result in serial):
        raise AssertionError("Reference serial workload contains an unexpected failure")
    if concurrent != serial:
        raise AssertionError("Concurrent replay changed a reference consumer result")
    if workload_digest(concurrent) != workload_digest(serial):
        raise AssertionError("Concurrent workload digest differs from serial baseline")
    if post_failure != serial:
        raise AssertionError("Failed consumers changed subsequent healthy results")

    serial_by_id = {result.request_id: result for result in serial}
    mixed_by_id = {result.request_id: result for result in mixed}
    valid_results_preserved = all(
        mixed_by_id[request.request_id] == serial_by_id[request.request_id]
        for request in valid_requests
    )
    if not valid_results_preserved:
        raise AssertionError("Mixed workload changed at least one healthy consumer result")

    failed_ids = [
        request.request_id
        for request in failure_requests
        if mixed_by_id[request.request_id].status == "ERROR"
    ]
    if set(failed_ids) != {request.request_id for request in failure_requests}:
        raise AssertionError("Failure-injection workload did not fail exactly the intended consumers")
    if any(mixed_by_id[request.request_id].error_type != "ReportingContractError" for request in failure_requests):
        raise AssertionError("Failure-injection requests did not fail through the reporting contract")

    hot = [result for result in serial if result.request_id.startswith("hot-dec-week-")]
    hot_payload_hashes = {result.response_payload_sha256 for result in hot}
    if len(hot_payload_hashes) != 1:
        raise AssertionError("Repeated hot-partition consumers did not receive identical payloads")

    finance_old = serial_by_id["finance-dec-v1-0"]
    finance_new = serial_by_id["finance-dec-v1-1"]
    cross_schema_core_hash_parity = finance_old.response_sha256 == finance_new.response_sha256
    if not cross_schema_core_hash_parity:
        raise AssertionError("Schema negotiation changed the finance query/data response hash")

    total_partitions = sum(int(result.partitions_selected or 0) for result in serial)
    total_rows = sum(int(result.rows_returned or 0) for result in serial)
    unique_partitions = sorted({key for result in serial for key in result.partition_keys})
    evidence = {
        "version": WORKLOAD_VERSION,
        "execution_model": "shared immutable store metadata + request-local ephemeral DuckDB connection",
        "valid_requests": len(valid_requests),
        "valid_consumers": len({request.consumer_id for request in valid_requests}),
        "max_workers": DEFAULT_MAX_WORKERS,
        "serial_concurrent_exact_result_parity": concurrent == serial,
        "serial_concurrent_workload_digest_parity": workload_digest(concurrent) == workload_digest(serial),
        "serial_workload_digest": workload_digest(serial),
        "concurrent_workload_digest": workload_digest(concurrent),
        "aggregate_metric_partitions_selected": total_partitions,
        "aggregate_metric_files_hashed": sum(int(result.metric_files_hashed or 0) for result in serial),
        "aggregate_rows_returned": total_rows,
        "unique_metric_partitions_touched": len(unique_partitions),
        "hot_partition_parallel_consumers": len(hot),
        "hot_partition_unique_payload_hashes": len(hot_payload_hashes),
        "cross_schema_core_hash_parity": cross_schema_core_hash_parity,
        "mixed_workload_requests": len(mixed_requests),
        "injected_failure_requests": len(failure_requests),
        "isolated_reporting_contract_failures": len(failed_ids),
        "healthy_results_preserved_in_mixed_workload": valid_results_preserved,
        "healthy_results_preserved_after_failures": post_failure == serial,
        "wall_clock_gate": False,
        "performance_claim_boundary": (
            "no QPS, latency, throughput or speedup gate is claimed from shared GitHub runners; "
            "the evidence contract is exact result isolation plus deterministic work accounting"
        ),
    }

    _write_json(root / "workload_isolation_requests.json", [request.to_dict() for request in mixed_requests])
    _write_json(root / "workload_isolation_serial_results.json", [result.to_dict() for result in serial])
    _write_json(root / "workload_isolation_concurrent_results.json", [result.to_dict() for result in concurrent])
    _write_json(root / "workload_isolation_mixed_results.json", [result.to_dict() for result in mixed])
    _write_json(root / "workload_isolation_evidence.json", evidence)
    print(json.dumps(evidence, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
