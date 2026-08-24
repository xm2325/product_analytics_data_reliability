from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd


def _bool(value: str) -> bool:
    lowered = value.strip().lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    raise ValueError(value)


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate checked-in v0.37 incremental claim ledger")
    parser.add_argument("output_dir", type=Path)
    parser.add_argument(
        "--ledger",
        type=Path,
        default=Path("results/incremental_reference_summary.csv"),
    )
    args = parser.parse_args()

    ledger_frame = pd.read_csv(args.ledger, dtype=str)
    if ledger_frame["claim"].duplicated().any():
        raise AssertionError("Duplicate incremental claim keys")
    claims = dict(zip(ledger_frame["claim"], ledger_frame["value"]))

    summary = json.loads((args.output_dir / "incremental_summary.json").read_text(encoding="utf-8"))
    recovery = json.loads(
        (args.output_dir / "incremental_recovery_evidence.json").read_text(encoding="utf-8")
    )
    performance = json.loads(
        (args.output_dir / "incremental_performance.json").read_text(encoding="utf-8")
    )
    manifest = pd.read_csv(args.output_dir / "incremental_source_partition_manifest.csv")
    work = performance["deterministic_work_reduction"]

    exact = {
        "version": summary["version"],
        "source_rows": str(summary["source_rows"]),
        "partition_count": str(summary["partition_count"]),
        "canonical_partition_bytes": str(performance["canonical_partition_bytes"]),
        "full_incremental_exact_parity": str(bool(summary["full_incremental_exact_parity"])).lower(),
        "idempotent_noop_rows_scanned": str(work["idempotent_noop_rows_scanned"]),
        "idempotent_noop_large_source_hashes_computed": str(
            work["idempotent_noop_large_source_hashes_computed"]
        ),
        "interruption_after_completed_partitions": str(recovery["interruption_after_completed_partitions"]),
        "durable_rows_reused_after_interruption": str(work["durable_rows_reused_after_interruption"]),
        "restart_partitions_skipped": str(work["restart_partitions_skipped"]),
        "restart_rows_scanned": str(work["restart_rows_scanned"]),
        "interrupted_resume_exact_parity": str(bool(summary["interrupted_resume_exact_parity"])).lower(),
        "targeted_repair_partition": str(work["targeted_repair_partition"]),
        "targeted_repair_rows_scanned": str(work["targeted_repair_rows_scanned"]),
        "targeted_repair_restored_exact_output_hashes": str(
            bool(recovery["targeted_repair_restored_exact_output_hashes"])
        ).lower(),
        "full_source_integrity_audit_hashes": str(summary["full_integrity_audit_source_hashes"]),
        "total_repository_tests": "88",
    }
    for key, expected in exact.items():
        observed = claims.get(key)
        if observed != expected:
            raise AssertionError(f"Claim {key!r}: ledger={observed!r}, generated={expected!r}")

    expected_repair_fraction = float(work["targeted_repair_scan_reduction_fraction"])
    observed_repair_fraction = float(claims["targeted_repair_scan_reduction_fraction"])
    if abs(observed_repair_fraction - expected_repair_fraction) > 1e-12:
        raise AssertionError("Targeted repair scan-reduction claim mismatch")

    if int(manifest["rows"].sum()) != int(claims["source_rows"]):
        raise AssertionError("Ledger source rows do not equal partition-manifest row sum")
    if len(manifest) != int(claims["partition_count"]):
        raise AssertionError("Ledger partition count does not equal partition manifest")
    repair_rows = int(
        manifest.loc[
            manifest["partition_key"] == claims["targeted_repair_partition"], "rows"
        ].iloc[0]
    )
    if repair_rows != int(claims["targeted_repair_rows_scanned"]):
        raise AssertionError("Ledger targeted repair rows do not match source partition")

    # Deliberately refuse to make runner wall-clock values stable public claims.
    timing_claims = [key for key in claims if "seconds" in key or "speedup" in key]
    if timing_claims:
        raise AssertionError(
            "Wall-clock timings/speedups are diagnostic shared-runner evidence and must not be pinned: "
            f"{timing_claims}"
        )

    # Ensure booleans are actually parseable, rather than accepting arbitrary strings.
    for key in [
        "full_incremental_exact_parity",
        "interrupted_resume_exact_parity",
        "targeted_repair_restored_exact_output_hashes",
    ]:
        if _bool(claims[key]) is not True:
            raise AssertionError(f"Expected true claim: {key}")

    print(
        "Incremental static-claim validation passed: "
        f"{claims['source_rows']} rows, {claims['partition_count']} partitions, "
        f"noop={claims['idempotent_noop_rows_scanned']} rows, "
        f"repair={claims['targeted_repair_rows_scanned']} rows"
    )


if __name__ == "__main__":
    main()
