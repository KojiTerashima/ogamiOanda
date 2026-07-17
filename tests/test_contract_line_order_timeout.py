import pytest

from ogami_oanda.strategy.line import order_timeout_min_for_distance


@pytest.mark.contract
@pytest.mark.parametrize(
    ("distance_pips", "timeframe", "default_timeout", "expected"),
    [
        (3, "m5", 30, 15),
        (7, "M5", 30, 30),
        (12, "h1", 90, 45),
        (20, "h1", 90, 60),
        (20, "other", 30, 30),
    ],
)
def test_order_timeout_is_determined_by_distance_then_timeframe_cap(distance_pips, timeframe, default_timeout, expected):
    assert order_timeout_min_for_distance(
        distance_pips,
        timeframe,
        default_timeout,
        ((3, 15), (7, 30), (12, 45)),
        {"m5": 45, "h1": 60},
    ) == expected
