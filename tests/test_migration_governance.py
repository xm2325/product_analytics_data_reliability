from __future__ import annotations

import pandas as pd
import pytest

from product_analytics.contracts import event_contract
from product_analytics.migration_governance import (
    ContractClassification,
    classify_event_contract_change,
    dau_shadow_replay,
    decide_migration,
    migration_proposals,
    summarise_dau_shadow_replay,
)


def _gold() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "product": ["notes_app", "notes_app", "photo_editor"],
            "date": ["2026-01-01", "2026-01-02", "2026-01-01"],
            "dau": [100, 120, 200],
            "dau_legacy_any_event": [105, 126, 204],
            "paid_subscription": [10, 12, 20],
            "revenue_gbp": [50.0, 60.0, 100.0],
        }
    )


def test_reference_proposals_cover_additive_breaking_and_semantic_changes() -> None:
    current = event_contract()
    proposals = migration_proposals()
    observed = {
        name: classify_event_contract_change(current, proposal).classification
        for name, proposal in proposals.items()
    }
    assert observed == {
        "add_optional_country": "ADDITIVE",
        "rename_required_event_id": "BREAKING",
        "broaden_dau_to_any_event": "SEMANTIC",
    }


def test_new_required_column_is_breaking_for_existing_producers() -> None:
    current = event_contract()
    proposed = dict(current)
    proposed["required_columns"] = [*current["required_columns"], "country"]
    result = classify_event_contract_change(current, proposed)
    assert result.classification == "BREAKING"
    assert result.producer_compatible is False


def test_shadow_replay_detects_semantic_dau_inflation_without_moving_money_metrics() -> None:
    replay = dau_shadow_replay(_gold())
    summary = summarise_dau_shadow_replay(replay)
    notes = summary.loc[summary["product"].eq("notes_app")].iloc[0]
    assert notes["portfolio_weighted_dau_delta_pct"] == pytest.approx(11 / 220)
    assert notes["max_abs_paid_delta"] == 0
    assert notes["max_abs_revenue_delta_gbp"] == 0


def test_additive_contract_can_pass_when_shadow_metrics_are_invariant() -> None:
    classification = ContractClassification("ADDITIVE", True, ("optional country added",))
    decision = decide_migration(
        "add_optional_country",
        classification,
        max_abs_metric_delta_pct=0.0,
        forecast_eligibility_changed=False,
    )
    assert decision.approved is True
    assert decision.action == "APPROVE"


def test_semantic_change_is_withheld_when_metric_delta_exceeds_tolerance() -> None:
    classification = ContractClassification("SEMANTIC", True, ("activity semantics changed",))
    decision = decide_migration(
        "broaden_dau_to_any_event",
        classification,
        max_abs_metric_delta_pct=0.021,
        forecast_eligibility_changed=False,
    )
    assert decision.approved is False
    assert decision.metric_invariance_gate is False
    assert decision.action == "WITHHOLD"


def test_forecast_eligibility_change_cannot_be_compensated_by_small_metric_delta() -> None:
    classification = ContractClassification("SEMANTIC", True, ("activity semantics changed",))
    decision = decide_migration(
        "semantic_candidate",
        classification,
        max_abs_metric_delta_pct=0.005,
        forecast_eligibility_changed=True,
    )
    assert decision.approved is False
    assert decision.metric_invariance_gate is True
    assert decision.forecast_eligibility_gate is False
