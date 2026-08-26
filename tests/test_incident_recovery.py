from __future__ import annotations

from datetime import timedelta

import pandas as pd
import pytest

from product_analytics.incident_recovery import (
    ACTIVE,
    ACTIVE_UNCHANGED,
    SOURCE_DATA_CORRECTION,
    SUPERSEDED,
    affected_product_dates,
    apply_product_routing_correction,
    build_decision_supersession_ledger,
    inject_product_routing_incident,
    selective_recompute_gold,
)
from product_analytics.metrics import daily_metrics


def _events() -> pd.DataFrame:
    rows = []
    event_id = 0
    for day in pd.date_range("2026-04-10", periods=3, freq="D", tz="UTC"):
        for product, prefix in [("notes_app", "n"), ("file_transfer", "f"), ("photo_editor", "p")]:
            event_id += 1
            rows.append(
                {
                    "event_id": f"e{event_id}",
                    "user_id": f"{prefix}-new",
                    "product": product,
                    "event_type": "first_open",
                    "event_ts": day,
                    "ingested_at": day + timedelta(minutes=1),
                    "revenue_gbp": 0.0,
                }
            )
            for user in range(3):
                hour = int(user) + 1
                event_id += 1
                rows.append(
                    {
                        "event_id": f"e{event_id}",
                        "user_id": f"{prefix}{user}",
                        "product": product,
                        "event_type": "app_open",
                        "event_ts": day + timedelta(hours=hour),
                        "ingested_at": day + timedelta(hours=hour, minutes=1),
                        "revenue_gbp": 0.0,
                    }
                )
            event_id += 1
            rows.append(
                {
                    "event_id": f"e{event_id}",
                    "user_id": f"{prefix}-buyer",
                    "product": product,
                    "event_type": "purchase",
                    "event_ts": day + timedelta(hours=12),
                    "ingested_at": day + timedelta(hours=12, minutes=1),
                    "revenue_gbp": 5.0,
                }
            )
    return pd.DataFrame(rows)


def _inject(events: pd.DataFrame):
    return inject_product_routing_incident(
        events,
        source_product="notes_app",
        incident_product="file_transfer",
        event_type="app_open",
        start_date="2026-04-10",
        end_date="2026-04-11",
    )


def test_routing_incident_changes_only_matching_rows_and_keeps_event_identity():
    clean = _events()
    incident, ledger = _inject(clean)
    assert len(incident) == len(clean)
    assert incident["event_id"].tolist() == clean["event_id"].tolist()
    assert len(ledger) == 6
    assert set(ledger["original_product"]) == {"notes_app"}
    assert set(ledger["incident_product"]) == {"file_transfer"}
    changed = incident["product"].ne(clean["product"])
    assert changed.sum() == 6
    assert set(incident.loc[changed, "event_type"]) == {"app_open"}


def test_event_id_correction_restores_clean_silver_exactly():
    clean = _events()
    incident, ledger = _inject(clean)
    corrected = apply_product_routing_correction(incident, ledger)
    pd.testing.assert_frame_equal(corrected, clean, check_exact=True)


def test_affected_product_dates_include_both_source_and_incident_products():
    _, ledger = _inject(_events())
    affected = affected_product_dates(ledger)
    assert len(affected) == 4
    assert set(affected["product"]) == {"notes_app", "file_transfer"}
    assert set(map(str, affected["date"])) == {"2026-04-10", "2026-04-11"}


def test_selective_gold_replay_equals_clean_full_rebuild():
    clean = _events()
    clean_gold = daily_metrics(clean)
    incident, ledger = _inject(clean)
    incident_gold = daily_metrics(incident)
    corrected = apply_product_routing_correction(incident, ledger)
    affected = affected_product_dates(ledger)
    selective, recomputed = selective_recompute_gold(incident_gold, corrected, affected)
    clean_rebuild = daily_metrics(corrected)

    # Core gate remains strict: the complete selectively repaired Gold product must
    # be exactly the same as a clean full rebuild, including dtypes.
    pd.testing.assert_frame_equal(selective, clean_rebuild, check_exact=True)
    pd.testing.assert_frame_equal(selective, clean_gold, check_exact=True)
    assert len(recomputed) == 4

    # Unaffected row values are reused exactly. A DataFrame column dtype is global,
    # so correcting zero-DAU rows can legitimately restore a ratio column from
    # object to float64 even for an extracted unaffected subset.
    photo_before = incident_gold.loc[incident_gold["product"].eq("photo_editor")].reset_index(drop=True)
    photo_after = selective.loc[selective["product"].eq("photo_editor")].reset_index(drop=True)
    pd.testing.assert_frame_equal(photo_before, photo_after, check_exact=True, check_dtype=False)


def test_correction_fails_closed_when_ledger_no_longer_matches_incident():
    incident, ledger = _inject(_events())
    tampered = ledger.copy()
    tampered.loc[0, "incident_product"] = "photo_editor"
    with pytest.raises(ValueError, match="no longer matches"):
        apply_product_routing_correction(incident, tampered)

    unknown = ledger.copy()
    unknown.loc[0, "event_id"] = "missing-event"
    with pytest.raises(ValueError, match="unknown event ids"):
        apply_product_routing_correction(incident, unknown)


def test_decision_supersession_versions_changed_evidence_and_retains_unaffected():
    incident = pd.DataFrame(
        [
            {"metric": "file_transfer:dau", "approved": False, "wape": 0.30},
            {"metric": "notes_app:dau", "approved": True, "wape": 0.04},
        ]
    )
    corrected = pd.DataFrame(
        [
            {"metric": "file_transfer:dau", "approved": True, "wape": 0.05},
            {"metric": "notes_app:dau", "approved": True, "wape": 0.04},
        ]
    )
    ledger = build_decision_supersession_ledger(incident, corrected)

    file_rows = ledger.loc[ledger["metric"].eq("file_transfer:dau")]
    assert set(file_rows["status"]) == {SUPERSEDED, ACTIVE}
    old = file_rows.loc[file_rows["status"].eq(SUPERSEDED)].iloc[0]
    new = file_rows.loc[file_rows["status"].eq(ACTIVE)].iloc[0]
    assert old["superseded_by"] == new["decision_id"]
    assert new["supersedes"] == old["decision_id"]
    assert old["supersession_reason"] == SOURCE_DATA_CORRECTION
    assert bool(old["action_changed"])

    notes = ledger.loc[ledger["metric"].eq("notes_app:dau")]
    assert len(notes) == 1
    assert notes.iloc[0]["status"] == ACTIVE_UNCHANGED
