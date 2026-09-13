from __future__ import annotations

import math
import sys
from pathlib import Path

import pandas as pd
import pytest

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "src"))

from core import (  # noqa: E402
    assert_no_leakage,
    parse_money,
    population_stability_index,
    wape,
)


def test_parse_money():
    assert parse_money("£1,234.50") == 1234.50
    assert parse_money("$98.00") == 98.0
    assert math.isnan(parse_money(None))


def test_leakage_guard_accepts_safe_features():
    assert_no_leakage(["lead_time", "hotel", "average_daily_rate"])


def test_leakage_guard_rejects_status_fields():
    with pytest.raises(ValueError):
        assert_no_leakage(["lead_time", "reservation_status"])


def test_psi_is_zero_for_same_distribution():
    x = pd.Series(range(100))
    assert population_stability_index(x, x) < 1e-9


def test_psi_detects_shift():
    reference = pd.Series(range(100))
    shifted = pd.Series(range(100, 200))
    assert population_stability_index(reference, shifted) > 0.2


def test_wape():
    assert abs(wape([100, 100], [90, 110]) - 0.1) < 1e-12
