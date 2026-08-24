from product_analytics.evidence_planning import count_jump_cycle_trials


def test_count_jump_cycle_treats_roundtrip_integer_reciprocals_as_exact():
    assert count_jump_cycle_trials(float("0.0074074074074074")) == 135
    assert count_jump_cycle_trials(float("0.003003003003003")) == 333


def test_count_jump_cycle_keeps_noninteger_reciprocal_ceiling():
    assert count_jump_cycle_trials(0.00497740267744034) == 201
    assert count_jump_cycle_trials(0.004863617458038721) == 206


def test_count_jump_cycle_zero_rate_uses_single_trial_cycle():
    assert count_jump_cycle_trials(0.0) == 1
