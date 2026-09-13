from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "src"))

from run_pipeline import split_by_booking_date  # noqa: E402


def test_booking_time_split_respects_all_boundaries():
    df = pd.DataFrame(
        {
            "booking_date": pd.to_datetime(
                [
                    "2016-06-30",
                    "2016-07-01",
                    "2016-09-30",
                    "2016-10-01",
                    "2016-12-31",
                    "2017-01-01",
                ]
            ),
            "value": range(6),
        }
    )

    train, calibration, validation, test = split_by_booking_date(df)

    assert train["value"].tolist() == [0]
    assert calibration["value"].tolist() == [1, 2]
    assert validation["value"].tolist() == [3, 4]
    assert test["value"].tolist() == [5]

    assert train["booking_date"].max() < pd.Timestamp("2016-07-01")
    assert calibration["booking_date"].min() >= pd.Timestamp("2016-07-01")
    assert calibration["booking_date"].max() < pd.Timestamp("2016-10-01")
    assert validation["booking_date"].min() >= pd.Timestamp("2016-10-01")
    assert validation["booking_date"].max() < pd.Timestamp("2017-01-01")
    assert test["booking_date"].min() >= pd.Timestamp("2017-01-01")
