from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path

import pandas as pd

from product_analytics.evidence_invalidation import (
    build_reference_graph,
    propagate_invalidation,
    root_fingerprints,
    serialise_graph,
    summarise_invalidation,
)


VERSION = "0.41.0"
PRICING_CHAIN = {"experiment:pricing", "impact:pricing", "authorisation:pricing"}


def _read_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def build_reference(base_dir: Path, output_dir: Path) -> dict[str, object]:
    required = [
        "event_contract.json",
        "migration_proposals.json",
        "migration_decisions.json",
        "forecast_evaluations.csv",
        "pricing_experiment_decision.json",
        "pricing_impact_decision.json",
    ]
    missing = [name for name in required if not (base_dir / name).is_file()]
    if missing:
        raise FileNotFoundError(f"Base controlled evidence is incomplete: {missing}")

    current_contract = _read_json(base_dir / "event_contract.json")
    proposals = _read_json(base_dir / "migration_proposals.json")
    migration_payload = _read_json(base_dir / "migration_decisions.json")
    experiment_payload = _read_json(base_dir / "pricing_experiment_decision.json")
    impact_payload = _read_json(base_dir / "pricing_impact_decision.json")
    forecast_rows = pd.read_csv(base_dir / "forecast_evaluations.csv").to_dict(orient="records")

    if not isinstance(current_contract, dict) or not isinstance(proposals, dict):
        raise TypeError("Controlled contract evidence must be JSON objects")
    if not isinstance(migration_payload, dict):
        raise TypeError("Migration decision evidence must be a JSON object")
    if not isinstance(experiment_payload, dict) or not isinstance(impact_payload, dict):
        raise TypeError("Pricing decision evidence must be JSON objects")

    migration_actions = {
        str(item["proposal"]): str(item["action"])
        for item in migration_payload.get("decisions", [])
    }
    if set(migration_actions) != set(proposals):
        raise ValueError("Migration proposals and decision evidence disagree")

    nodes = build_reference_graph(
        event_contract_payload=current_contract,
        forecast_rows=forecast_rows,
        experiment_payload=experiment_payload,
        impact_payload=impact_payload,
    )
    output_dir.mkdir(parents=True, exist_ok=True)

    graph_payload = {
        "version": VERSION,
        "policy": {
            "freshness_rule": "evidence is fresh only when its own governed fingerprint and every dependency remain fresh",
            "stale_action": "WITHHOLD_STALE",
            "optional_unused_fields_invalidate": False,
            "downstream_decisions_can_compensate_for_semantic_change": False,
            "claim_boundary": "controlled dependency invalidation evidence; not a production lineage service or scheduler",
        },
        "baseline_root_fingerprints": root_fingerprints(current_contract),
        "nodes": serialise_graph(nodes),
    }
    _write_json(output_dir / "evidence_dependency_graph.json", graph_payload)

    detail_rows: list[dict[str, object]] = []
    summary_rows: list[dict[str, object]] = []
    scenario_payloads: dict[str, object] = {}
    for proposal_name in sorted(proposals):
        proposal = proposals[proposal_name]
        if not isinstance(proposal, dict):
            raise TypeError(f"Migration proposal {proposal_name} must be a JSON object")
        candidate_roots = root_fingerprints(proposal)
        records = propagate_invalidation(nodes, candidate_roots)
        summary = summarise_invalidation(records)
        by_id = {record.node_id: record for record in records}
        pricing_chain_fresh = all(by_id[node_id].status == "FRESH" for node_id in PRICING_CHAIN)
        direct_changed_roots = sorted(
            record.node_id for record in records if record.direct_fingerprint_changed
        )
        summary_row = {
            "proposal": proposal_name,
            "migration_action": migration_actions[proposal_name],
            "nodes": summary["nodes"],
            "fresh": summary["fresh"],
            "direct_stale": summary["direct_stale"],
            "downstream_stale": summary["downstream_stale"],
            "total_stale": summary["total_stale"],
            "pricing_chain_fresh": pricing_chain_fresh,
            "direct_changed_roots": ";".join(direct_changed_roots),
            "stale_node_ids": ";".join(summary["stale_node_ids"]),
        }
        summary_rows.append(summary_row)
        scenario_payloads[proposal_name] = {
            "migration_action": migration_actions[proposal_name],
            "candidate_root_fingerprints": candidate_roots,
            "summary": summary,
            "pricing_chain_fresh": pricing_chain_fresh,
            "direct_changed_roots": direct_changed_roots,
        }
        for record in records:
            row = asdict(record)
            row.update(
                {
                    "proposal": proposal_name,
                    "migration_action": migration_actions[proposal_name],
                    "stale_dependencies": ";".join(record.stale_dependencies),
                }
            )
            detail_rows.append(row)

    summary_frame = pd.DataFrame(summary_rows).sort_values("proposal").reset_index(drop=True)
    detail_frame = pd.DataFrame(detail_rows).sort_values(["proposal", "node_id"]).reset_index(drop=True)
    summary_frame.to_csv(output_dir / "evidence_invalidation_summary.csv", index=False)
    detail_frame.to_csv(output_dir / "evidence_invalidation_scenarios.csv", index=False)
    _write_json(
        output_dir / "evidence_invalidation_evidence.json",
        {
            "version": VERSION,
            "base_reference_version": migration_payload.get("version"),
            "scenarios": scenario_payloads,
        },
    )

    return {
        "version": VERSION,
        "nodes": len(nodes),
        "scenarios": len(summary_frame),
        "stale_counts": {
            row["proposal"]: int(row["total_stale"]) for row in summary_rows
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build v0.41 selective downstream evidence-invalidation reference"
    )
    parser.add_argument("--base-dir", default="build/reference")
    parser.add_argument("--output-dir", default="build/evidence-invalidation")
    args = parser.parse_args()
    result = build_reference(Path(args.base_dir), Path(args.output_dir))
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
