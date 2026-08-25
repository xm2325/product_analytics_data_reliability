from __future__ import annotations

import argparse
from pathlib import Path
import json

import pandas as pd


DEFAULT_LEDGER = Path("results/workload_isolation_reference_summary.csv")


def _normalise(value: object) -> str:
    if isinstance(value, bool):
        return str(value).lower()
    return str(value)


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate checked-in v0.40 workload-isolation claims")
    parser.add_argument("incremental_dir", type=Path)
    parser.add_argument("--ledger", type=Path, default=DEFAULT_LEDGER)
    args = parser.parse_args()

    evidence = json.loads((args.incremental_dir / "workload_isolation_evidence.json").read_text(encoding="utf-8"))
    ledger = pd.read_csv(args.ledger, dtype=str)
    if ledger["claim"].duplicated().any():
        raise AssertionError("Duplicate workload-isolation claim keys")
    claims = dict(zip(ledger["claim"], ledger["value"]))

    forbidden = ("seconds", "latency", "qps", "throughput", "speedup")
    if any(any(token in key.lower() for token in forbidden) for key in claims):
        raise AssertionError("Shared-runner wall-clock/throughput values must not be pinned as workload claims")

    for key, expected in claims.items():
        if key not in evidence:
            raise AssertionError(f"Pinned workload claim {key!r} is absent from generated evidence")
        observed = _normalise(evidence[key])
        if observed != expected:
            raise AssertionError(f"Workload claim {key!r}: ledger={expected!r}, generated={observed!r}")

    required_true = (
        "serial_concurrent_exact_result_parity",
        "serial_concurrent_workload_digest_parity",
        "cross_schema_core_hash_parity",
        "healthy_results_preserved_in_mixed_workload",
        "healthy_results_preserved_after_failures",
    )
    for key in required_true:
        if evidence.get(key) is not True:
            raise AssertionError(f"Required workload isolation gate {key!r} did not pass")
    if evidence.get("wall_clock_gate") is not False:
        raise AssertionError("Shared-runner wall clock must remain outside the workload gate")

    print(
        "Workload static-claim validation passed: "
        f"{len(claims)} pinned deterministic claims"
    )


if __name__ == "__main__":
    main()
