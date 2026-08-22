import pytest

from product_analytics.risk_design import (
    DesignCandidate,
    RiskBudget,
    allocation_counts,
    select_design,
    variance_adjusted_information,
)


def test_20_80_allocation_matches_reference_information_count():
    total, treated, control = allocation_counts(700, 0.20)
    assert total == 1094
    assert treated == 219
    assert control == 875


def test_selection_is_lexicographic_after_constraints():
    candidates = [
        DesignCandidate(0.30, 700, 834, 250, 584, 220, 1300, 4.0, 0.59),
        DesignCandidate(0.20, 700, 1094, 219, 875, 270, 1326, 4.17, 0.598),
        DesignCandidate(0.15, 700, 1373, 206, 1167, 350, 1800, 3.9, 0.57),
    ]
    selected = select_design(candidates, RiskBudget())
    assert selected.treatment_share == 0.20


def test_no_feasible_candidate_raises():
    bad = [DesignCandidate(0.20, 700, 1094, 219, 875, 400, 1900, 6.0, 0.70)]
    with pytest.raises(ValueError):
        select_design(bad)


def test_higher_treatment_variance_reduces_information():
    base = variance_adjusted_information(875, 219, 1.0)
    stressed = variance_adjusted_information(875, 219, 1.1)
    assert stressed < base
