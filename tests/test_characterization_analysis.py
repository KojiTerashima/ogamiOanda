import pytest

from classCandlePeaks import PeaksClass
from fLineAnalysis import LineOrderCoordinator


@pytest.mark.characterization
def test_peak_calculation_preserves_reversed_candle_contract(candle_frame):
    calculator = object.__new__(PeaksClass)
    calculator.minimum = 0.0000001
    calculator.ps_default = 5
    calculator.df_r_original = candle_frame
    calculator.df_r_copy = candle_frame.copy()
    calculator.current_price = 150.30
    calculator.round_price = lambda value: round(value, 3)
    calculator.check_large_body_in_peak = lambda peak: {
        "include_large": False,
        "include_very_large": False,
        "highest": 150.33,
        "lowest": 149.97,
    }

    peak = calculator.make_peak(candle_frame)

    assert peak["direction"] == 1
    assert peak["count"] == 4
    assert peak["latest_time_jp"] == "2026/01/02 00:25:00"
    assert peak["latest_body_peak_price"] == 150.31
    assert peak["peak"] == peak["latest_body_peak_price"]


@pytest.mark.unit
def test_line_session_and_sorting_contract():
    assert LineOrderCoordinator.get_session_info("2026/01/02 06:00:00")["session_name"] == "morning"
    assert LineOrderCoordinator.get_session_info("2026/01/02 12:00:00")["session_name"] == "day"
    assert LineOrderCoordinator.get_session_info("2026/01/02 18:00:00")["session_name"] == "night"

    lines = [{"price": 149.8}, {"price": 150.4}, {"price": 150.1}]
    assert LineOrderCoordinator._sorted_ahead_lines(lines, 150.0, 1) == [
        {"price": 150.1},
        {"price": 150.4},
    ]
