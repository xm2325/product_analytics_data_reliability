from __future__ import annotations

import pandas as pd

from product_analytics.real_retail import build_daily_metrics, semantic_comparison


def _toy_canonical() -> pd.DataFrame:
    frame = pd.DataFrame(
        {
            "source_row_id": [0, 1, 2],
            "invoice_no": pd.Series(["100001", "C100001", "100002"], dtype="string"),
            "stock_code": pd.Series(["A", "A", "B"], dtype="string"),
            "description": pd.Series(["item a", "item a", "item b"], dtype="string"),
            "quantity": [2.0, -1.0, 1.0],
            "invoice_ts": pd.to_datetime(["2011-01-01 10:00", "2011-01-02 10:00", "2011-01-03 10:00"]),
            "unit_price_gbp": [10.0, 10.0, 5.0],
            "customer_id": pd.Series(["10", "10", pd.NA], dtype="string"),
            "country": pd.Series(["United Kingdom"] * 3, dtype="string"),
            "source_sheet": ["toy"] * 3,
            "is_cancellation": [False, True, False],
            "line_value_gbp": [20.0, -10.0, 5.0],
            "is_purchase_line": [True, False, True],
            "is_identified_purchase_line": [True, False, False],
        }
    )
    return frame


def test_daily_metrics_fill_calendar_and_keep_missing_customer_out_of_customer_metric() -> None:
    daily = build_daily_metrics(_toy_canonical())
    assert daily["date"].astype(str).tolist() == ["2011-01-01", "2011-01-02", "2011-01-03"]
    assert daily["revenue_gbp"].tolist() == [20.0, 0.0, 5.0]
    assert daily["orders"].tolist() == [1.0, 0.0, 1.0]
    assert daily["active_customers"].tolist() == [1.0, 0.0, 0.0]


def test_signed_ledger_is_not_a_backward_compatible_revenue_replacement() -> None:
    comparison = semantic_comparison(_toy_canonical()).set_index("metric")
    revenue = comparison.loc["revenue_gbp"]
    assert revenue["current_value"] == 25.0
    assert revenue["candidate_value"] == 15.0
    assert revenue["relative_delta"] == -0.4
    assert bool(revenue["backward_compatible"]) is False
    assert revenue["replacement_action"] == "WITHHOLD_AS_DROP_IN_REPLACEMENT"


def test_customer_population_can_be_backward_compatible_even_when_revenue_is_not() -> None:
    comparison = semantic_comparison(_toy_canonical()).set_index("metric")
    customers = comparison.loc["active_customer_population"]
    assert customers["current_value"] == 1.0
    assert customers["candidate_value"] == 1.0
    assert customers["relative_delta"] == 0.0
    assert bool(customers["backward_compatible"]) is True
