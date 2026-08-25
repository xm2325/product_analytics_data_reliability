from __future__ import annotations

import argparse
from datetime import date
from hashlib import sha256
from pathlib import Path
import json

import pandas as pd


EXPECTED_LEDGER = Path("results/reporting_reference_summary.csv")
INTEGER_METRICS = {"orders", "purchase_lines", "active_customers"}


def _sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _expected_records(
    daily: pd.DataFrame,
    start: date,
    end: date,
    metrics: list[str],
) -> list[dict[str, object]]:
    frame = daily.copy()
    frame["date"] = pd.to_datetime(frame["date"]).dt.date
    frame = frame.loc[
        (frame["date"] >= start) & (frame["date"] <= end),
        ["date", *metrics],
    ]
    rows: list[dict[str, object]] = []
    for row in frame.to_dict("records"):
        out: dict[str, object] = {"date": row["date"].isoformat()}
        for metric in metrics:
            out[metric] = (
                int(row[metric])
                if metric in INTEGER_METRICS
                else float(row[metric])
            )
        rows.append(out)
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Independently validate v0.38 reporting-product evidence"
    )
    parser.add_argument("incremental_dir", type=Path)
    parser.add_argument("--ledger", type=Path, default=EXPECTED_LEDGER)
    args = parser.parse_args()
    root = args.incremental_dir

    contract = json.loads(
        (root / "reporting_contract.json").read_text(encoding="utf-8")
    )
    catalog = json.loads(
        (root / "reporting_metric_catalog.json").read_text(encoding="utf-8")
    )
    sample = json.loads(
        (root / "reporting_sample_query.json").read_text(encoding="utf-8")
    )
    evidence = json.loads(
        (root / "reporting_evidence.json").read_text(encoding="utf-8")
    )
    daily = pd.read_csv(root / "incremental_daily_metrics.csv")
    manifest = pd.read_csv(root / "incremental_source_partition_manifest.csv")
    state = json.loads(
        (root / "incremental_state.json").read_text(encoding="utf-8")
    )

    if contract["version"] != "0.38.0" or contract["schema_version"] != "1.0":
        raise AssertionError("Unexpected reporting contract version")
    names = [row["name"] for row in catalog]
    expected_names = [
        "revenue_gbp",
        "orders",
        "units",
        "purchase_lines",
        "active_customers",
    ]
    if names != expected_names:
        raise AssertionError(f"Unexpected metric catalog: {names}")
    if int(contract["max_query_days"]) != 366:
        raise AssertionError("Unexpected reporting query-width contract")

    start = date.fromisoformat(sample["query"]["start_date"])
    end = date.fromisoformat(sample["query"]["end_date"])
    metrics = list(sample["query"]["metrics"])
    expected_rows = _expected_records(daily, start, end, metrics)
    if sample["data"] != expected_rows:
        raise AssertionError(
            "Sample response does not independently reconcile to incremental_daily_metrics.csv"
        )
    if sample["row_count"] != len(expected_rows):
        raise AssertionError("Sample response row_count mismatch")

    digest_payload = json.dumps(
        {"query": sample["query"], "data": sample["data"]},
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    if sample["response_sha256"] != sha256(digest_payload).hexdigest():
        raise AssertionError("Sample response digest mismatch")

    expected_key = f"{start.year:04d}-{start.month:02d}"
    if start.month != end.month or start.year != end.year:
        raise AssertionError("Pinned sample query should stay inside one month")
    if [row["partition_key"] for row in sample["partition_provenance"]] != [
        expected_key
    ]:
        raise AssertionError(
            "Sample query did not expose exactly the expected partition provenance"
        )

    state_row = state["partitions"][expected_key]
    manifest_row = manifest.loc[
        manifest["partition_key"].astype(str) == expected_key
    ].iloc[0]
    if str(state_row["source_sha256"]) != str(manifest_row["sha256"]):
        raise AssertionError("Selected partition source binding mismatch")
    metric_path = root / "metric_partitions" / str(state_row["metric_path"])
    observed_metric_sha = _sha256_file(metric_path)
    if observed_metric_sha != state_row["metric_sha256"]:
        raise AssertionError("Selected partition metric SHA mismatch")
    if sample["partition_provenance"][0]["metric_sha256"] != observed_metric_sha:
        raise AssertionError("Sample provenance did not expose selected metric SHA")

    ledger_frame = pd.read_csv(args.ledger, dtype=str)
    if ledger_frame["claim"].duplicated().any():
        raise AssertionError("Duplicate reporting claim keys")
    claims = dict(zip(ledger_frame["claim"], ledger_frame["value"]))
    generated = {
        "version": str(evidence["version"]),
        "schema_version": str(evidence["schema_version"]),
        "metric_count": str(evidence["metric_count"]),
        "metric_store_partitions": str(evidence["metric_store_partitions"]),
        "initialisation_boundary_partitions_read": str(
            evidence["initialisation_boundary_partitions_read"]
        ),
        "sample_query_days": str(evidence["sample_query_days"]),
        "sample_query_metric_partitions": str(
            evidence["sample_query_metric_partitions"]
        ),
        "sample_query_metric_files_hashed": str(
            evidence["sample_query_metric_files_hashed"]
        ),
        "sample_query_exact_parity": str(
            bool(evidence["sample_query_exact_parity"])
        ).lower(),
        "cross_month_metric_partitions": str(
            evidence["cross_month_metric_partitions"]
        ),
        "unknown_metric_rejected": str(
            bool(evidence["unknown_metric_rejected"])
        ).lower(),
        "overwide_query_rejected": str(
            bool(evidence["overwide_query_rejected"])
        ).lower(),
        "tamper_rejected_before_serve": str(
            bool(evidence["tamper_rejected_before_serve"])
        ).lower(),
        "max_query_days": str(evidence["max_query_days"]),
        "no_ingestion_time_claim": str(
            bool(evidence["no_ingestion_time_claim"])
        ).lower(),
    }
    for key, expected in generated.items():
        if claims.get(key) != expected:
            raise AssertionError(
                f"Reporting claim {key!r}: ledger={claims.get(key)!r}, generated={expected!r}"
            )
    observed_reduction = float(
        claims["sample_query_partition_reduction_fraction"]
    )
    expected_reduction = float(
        evidence["sample_query_partition_reduction_fraction"]
    )
    if abs(observed_reduction - expected_reduction) > 1e-12:
        raise AssertionError("Sample partition-reduction claim mismatch")
    if any("seconds" in key or "latency" in key for key in claims):
        raise AssertionError(
            "Shared-runner wall-clock values must not be pinned as reporting claims"
        )

    print(
        "Reporting-product validation passed: "
        f"{len(catalog)} metrics, {len(manifest)} store partitions, "
        f"sample={sample['row_count']} days / "
        f"{len(sample['partition_provenance'])} partition"
    )


if __name__ == "__main__":
    main()
