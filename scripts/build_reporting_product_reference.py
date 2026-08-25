from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path
import json
import shutil

import pandas as pd

from product_analytics.reporting_product import (
    MAX_QUERY_DAYS,
    MetricQuery,
    ReportingContractError,
    RetailMetricStore,
    metric_catalog,
    reporting_contract,
)


def _write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _expected_records(
    daily: pd.DataFrame,
    start: date,
    end: date,
    metrics: tuple[str, ...],
) -> list[dict[str, object]]:
    frame = daily.copy()
    frame["date"] = pd.to_datetime(frame["date"]).dt.date
    frame = frame.loc[
        (frame["date"] >= start) & (frame["date"] <= end),
        ["date", *metrics],
    ].copy()
    records: list[dict[str, object]] = []
    integer_metrics = {"orders", "purchase_lines", "active_customers"}
    for row in frame.to_dict("records"):
        out: dict[str, object] = {"date": row["date"].isoformat()}
        for metric in metrics:
            value = row[metric]
            out[metric] = int(value) if metric in integer_metrics else float(value)
        records.append(out)
    return records


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build v0.39 reporting-data-product evidence from v0.37 incremental metrics"
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
    daily_path = root / "incremental_daily_metrics.csv"
    for required in [metric_dir, state_path, source_manifest_path, daily_path]:
        if not required.exists():
            raise FileNotFoundError(required)

    daily = pd.read_csv(daily_path)
    sample_query = MetricQuery(
        start_date=date(2010, 12, 1),
        end_date=date(2010, 12, 7),
        metrics=(
            "revenue_gbp",
            "orders",
            "units",
            "purchase_lines",
            "active_customers",
        ),
    )
    cross_month_query = MetricQuery(
        start_date=date(2010, 11, 28),
        end_date=date(2010, 12, 4),
        metrics=("orders", "active_customers"),
    )

    with RetailMetricStore(metric_dir, state_path, source_manifest_path) as store:
        sample_response, sample_work = store.query(sample_query)
        cross_response, cross_work = store.query(cross_month_query)
        initialisation_boundary_partitions_read = (
            store.initialisation_boundary_partitions_read
        )
        available_start = store.available_start.isoformat()
        available_end = store.available_end.isoformat()

        expected = _expected_records(
            daily,
            sample_query.start_date,
            sample_query.end_date,
            sample_query.metrics,
        )
        sample_exact_parity = sample_response["data"] == expected
        if not sample_exact_parity:
            raise AssertionError(
                "Consumer sample query does not match the validated incremental daily layer"
            )

        unknown_metric_rejected = False
        try:
            store.query(
                MetricQuery(
                    date(2010, 12, 1),
                    date(2010, 12, 1),
                    ("profit",),
                )
            )
        except ReportingContractError:
            unknown_metric_rejected = True
        if not unknown_metric_rejected:
            raise AssertionError("Unknown metric was not rejected")

        overwide_query_rejected = False
        try:
            store.query(
                MetricQuery(
                    date(2009, 12, 1),
                    date(2011, 1, 1),
                    ("orders",),
                )
            )
        except ReportingContractError:
            overwide_query_rejected = True
        if not overwide_query_rejected:
            raise AssertionError("Over-wide consumer query was not rejected")

    source_manifest = pd.read_csv(source_manifest_path)
    partition_count = int(len(source_manifest))
    sample_partition_reduction_fraction = (
        1.0 - sample_work.partitions_selected / partition_count
    )

    tamper_root = root / "_reporting_tamper_case"
    if tamper_root.exists():
        shutil.rmtree(tamper_root)
    tamper_metric_dir = tamper_root / "metric_partitions"
    shutil.copytree(metric_dir, tamper_metric_dir)
    tamper_state = tamper_root / "incremental_state.json"
    tamper_manifest = tamper_root / "incremental_source_partition_manifest.csv"
    shutil.copy2(state_path, tamper_state)
    shutil.copy2(source_manifest_path, tamper_manifest)
    with (tamper_metric_dir / "2010-12.parquet").open("ab") as handle:
        handle.write(b"reporting-contract-tamper")
    tamper_rejected = False
    try:
        with RetailMetricStore(
            tamper_metric_dir,
            tamper_state,
            tamper_manifest,
        ) as tampered:
            tampered.query(
                MetricQuery(
                    date(2010, 12, 1),
                    date(2010, 12, 1),
                    ("orders",),
                )
            )
    except ReportingContractError:
        tamper_rejected = True
    if not tamper_rejected:
        raise AssertionError("Tampered metric partition was served")
    shutil.rmtree(tamper_root)

    contract = reporting_contract()
    catalog = metric_catalog()
    evidence = {
        "version": "0.39.0",
        "schema_version": contract["schema_version"],
        "metric_count": len(catalog),
        "metric_store_partitions": partition_count,
        "initialisation_boundary_partitions_read": (
            initialisation_boundary_partitions_read
        ),
        "available_start": available_start,
        "available_end": available_end,
        "sample_query_days": sample_work.rows_returned,
        "sample_query_metric_partitions": sample_work.partitions_selected,
        "sample_query_metric_files_hashed": sample_work.metric_files_hashed,
        "sample_query_partition_reduction_fraction": (
            sample_partition_reduction_fraction
        ),
        "sample_query_exact_parity": sample_exact_parity,
        "cross_month_query_rows": cross_work.rows_returned,
        "cross_month_metric_partitions": cross_work.partitions_selected,
        "cross_month_partition_keys": list(cross_work.partition_keys),
        "unknown_metric_rejected": unknown_metric_rejected,
        "overwide_query_rejected": overwide_query_rejected,
        "tamper_rejected_before_serve": tamper_rejected,
        "max_query_days": MAX_QUERY_DAYS,
        "no_ingestion_time_claim": True,
        "performance_boundary": (
            "stable evidence is partition selection/work avoided; "
            "shared-runner wall-clock is not a pass/fail claim"
        ),
    }

    _write_json(root / "reporting_contract.json", contract)
    _write_json(root / "reporting_metric_catalog.json", catalog)
    _write_json(root / "reporting_sample_query.json", sample_response)
    _write_json(root / "reporting_cross_month_query.json", cross_response)
    _write_json(root / "reporting_evidence.json", evidence)

    print(json.dumps(evidence, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
