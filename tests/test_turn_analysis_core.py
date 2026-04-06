from turn_analysis_core import evaluate_glass_shape_flags, latest_price_position_in_bb

# ===========================================================================
# latest_price_position_in_bb
# ===========================================================================


def test_latest_price_position_in_bb_upper_side():
    assert latest_price_position_in_bb(151.0, 149.0, 150.7) == 1


def test_latest_price_position_in_bb_lower_side():
    assert latest_price_position_in_bb(151.0, 149.0, 149.2) == -1


def test_latest_price_at_exact_midpoint_returns_negative_one():
    # diff_big == diff_small → condition diff_big < diff_small is False → -1
    result = latest_price_position_in_bb(152.0, 148.0, 150.0)
    assert result == -1


def test_latest_price_very_close_to_upper():
    assert latest_price_position_in_bb(100.0, 0.0, 99.9) == 1


def test_latest_price_very_close_to_lower():
    assert latest_price_position_in_bb(100.0, 0.0, 0.1) == -1


def test_latest_price_bands_tight_upper_biased():
    # Tiny bb range: upper=1.001, lower=1.000. price=1.0009 → closer to upper
    assert latest_price_position_in_bb(1.001, 1.000, 1.0009) == 1


def test_latest_price_bands_tight_lower_biased():
    assert latest_price_position_in_bb(1.001, 1.000, 1.0001) == -1


def test_latest_price_negative_price_values():
    # Negative prices should still work via abs()
    assert latest_price_position_in_bb(-1.0, -5.0, -1.5) == 1


# ===========================================================================
# evaluate_glass_shape_flags
# ===========================================================================


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


def test_evaluate_no_before_expansion():
    res = evaluate_glass_shape_flags(
        has_before_expansion=False,
        has_after_expansion=True,
        head_is_minimum=False,
        latest_count=3,
        before_expansion_rows=1,
    )
    assert res["result"] is False
    assert res["is_glass_shape"] is False
    assert res["is_glass_shape_long"] is False
    assert res["is_first_glass_shape"] is False


def test_evaluate_no_after_expansion():
    res = evaluate_glass_shape_flags(
        has_before_expansion=True,
        has_after_expansion=False,
        head_is_minimum=False,
        latest_count=3,
        before_expansion_rows=1,
    )
    assert res["result"] is False
    assert res["is_glass_shape"] is False


def test_evaluate_both_false():
    res = evaluate_glass_shape_flags(
        has_before_expansion=False,
        has_after_expansion=False,
        head_is_minimum=False,
        latest_count=3,
        before_expansion_rows=1,
    )
    assert res["result"] is False
    assert res["is_glass_shape"] is False


def test_evaluate_boundary_latest_count_4_is_not_long():
    # latest_count == 4 → is_glass_shape_long False (boundary: <= 4)
    res = evaluate_glass_shape_flags(
        has_before_expansion=True,
        has_after_expansion=True,
        head_is_minimum=False,
        latest_count=4,
        before_expansion_rows=1,
    )
    assert res["is_glass_shape_long"] is False
    assert res["is_glass_shape"] is True


def test_evaluate_boundary_latest_count_5_is_long():
    # latest_count == 5 → is_glass_shape_long True (boundary: > 4)
    res = evaluate_glass_shape_flags(
        has_before_expansion=True,
        has_after_expansion=True,
        head_is_minimum=False,
        latest_count=5,
        before_expansion_rows=1,
    )
    assert res["is_glass_shape_long"] is True
    assert res["is_first_glass_shape"] is True


def test_evaluate_first_glass_boundary_rows_equals_1():
    res = evaluate_glass_shape_flags(
        has_before_expansion=True,
        has_after_expansion=True,
        head_is_minimum=False,
        latest_count=3,
        before_expansion_rows=1,
    )
    assert res["is_first_glass_shape"] is True


def test_evaluate_not_first_glass_boundary_rows_greater_than_1():
    res = evaluate_glass_shape_flags(
        has_before_expansion=True,
        has_after_expansion=True,
        head_is_minimum=False,
        latest_count=3,
        before_expansion_rows=2,
    )
    assert res["is_first_glass_shape"] is False


def test_evaluate_head_is_minimum_suppresses_glass_even_with_long_count():
    res = evaluate_glass_shape_flags(
        has_before_expansion=True,
        has_after_expansion=True,
        head_is_minimum=True,
        latest_count=10,
        before_expansion_rows=1,
    )
    assert res["result"] is True   # expansion condition still holds
    assert res["is_glass_shape"] is False
    assert res["is_glass_shape_long"] is False
