def latest_price_position_in_bb(bb_upper: float, bb_lower: float, price: float) -> int:
    """Return 1 when price is closer to upper band, otherwise -1."""
    diff_big = abs(bb_upper - price)
    diff_small = abs(price - bb_lower)
    if diff_big < diff_small:
        return 1
    return -1


def evaluate_glass_shape_flags(
    *,
    has_before_expansion: bool,
    has_after_expansion: bool,
    head_is_minimum: bool,
    latest_count: int,
    before_expansion_rows: int,
) -> dict:
    """Calculate glass-shape flags from pre-computed conditions."""
    result = has_before_expansion and has_after_expansion
    if result and not head_is_minimum:
        if latest_count <= 4:
            is_glass_shape = True
            is_glass_shape_long = False
        else:
            is_glass_shape = True
            is_glass_shape_long = True
        is_first_glass_shape = before_expansion_rows == 1
    else:
        is_glass_shape = False
        is_glass_shape_long = False
        is_first_glass_shape = False

    return {
        "result": result,
        "is_glass_shape": is_glass_shape,
        "is_glass_shape_long": is_glass_shape_long,
        "is_first_glass_shape": is_first_glass_shape,
    }
