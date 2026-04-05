from turn_analysis_core import evaluate_glass_shape_flags, latest_price_position_in_bb


def test_latest_price_position_in_bb_upper_side():
    assert latest_price_position_in_bb(151.0, 149.0, 150.7) == 1


def test_latest_price_position_in_bb_lower_side():
    assert latest_price_position_in_bb(151.0, 149.0, 149.2) == -1


def test_evaluate_glass_shape_flags_first_normal_glass():
    res = evaluate_glass_shape_flags(
        has_before_expansion=True,
        has_after_expansion=True,
        head_is_minimum=False,
        latest_count=3,
        before_expansion_rows=1,
    )
    assert res["result"] is True
    assert res["is_glass_shape"] is True
    assert res["is_glass_shape_long"] is False
    assert res["is_first_glass_shape"] is True


def test_evaluate_glass_shape_flags_long_glass_not_first():
    res = evaluate_glass_shape_flags(
        has_before_expansion=True,
        has_after_expansion=True,
        head_is_minimum=False,
        latest_count=8,
        before_expansion_rows=2,
    )
    assert res["is_glass_shape"] is True
    assert res["is_glass_shape_long"] is True
    assert res["is_first_glass_shape"] is False


def test_evaluate_glass_shape_flags_invalid_when_head_is_min():
    res = evaluate_glass_shape_flags(
        has_before_expansion=True,
        has_after_expansion=True,
        head_is_minimum=True,
        latest_count=2,
        before_expansion_rows=1,
    )
    assert res["result"] is True
    assert res["is_glass_shape"] is False
    assert res["is_first_glass_shape"] is False
