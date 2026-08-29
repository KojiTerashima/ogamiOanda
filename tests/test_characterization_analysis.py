import pandas as pd
import pytest

from classCandlePeaks import (
    PeaksClass,
    _legacy_judge_peak_is_belong_peak_group,
    _LegacyPeaksClass,
)
from fLineAnalysis import LineOrderCoordinator
from ogami_oanda.domain.analysis.lines import LineGrouper, LineStrengthCalculator
from ogami_oanda.domain.analysis.peaks import (
    PeaksClass as DomainPeaksClass,
)
from ogami_oanda.domain.analysis.peaks import (
    judge_peak_is_belong_peak_group,
)
from ogami_oanda.strategy.line import (
    LineCandidateCoordinator,
    LineStrategyProfileUsdJpy,
    UsdJpyM5BreakoutLineOrderStrategy,
    UsdJpyM5LineOrderStrategy,
)


def _opposite_side_line_result(latest_direction, grouped_peaks):
    frame = pd.DataFrame(
        {
            "time_jp": [
                "2026/08/28 12:00:00",
                "2026/08/28 11:55:00",
                "2026/08/28 11:50:00",
                "2026/08/28 11:45:00",
            ],
            "close": [160.0, 160.0, 160.0, 160.0],
        }
    )
    latest_peak = {
        "latest_time_jp": "2026/08/28 12:05:00",
        "latest_body_peak_price": 160.0,
        "direction": latest_direction,
        "peak_strength": 2,
        "rsi": 50,
    }
    return LineStrengthCalculator("USD_JPY").calculate(
        foot="m5",
        peaks=[latest_peak, *grouped_peaks],
        frame=frame,
        current_price=160.0,
        current_time="2026/08/28 12:05:00",
        time_before_foot_count=60,
    )


@pytest.mark.unit
@pytest.mark.parametrize(
    ("latest_direction", "line_side", "line_price"),
    ((1, "lower", 159.9), (-1, "upper", 160.1)),
)
def test_line_strength_marks_non_flipped_opposite_side_before_candidate_build(
    latest_direction,
    line_side,
    line_price,
):
    result = _opposite_side_line_result(
        latest_direction,
        [
            {
                "latest_time_jp": "2026/08/28 11:55:00",
                "latest_body_peak_price": line_price,
                "direction": -latest_direction,
                "peak_strength": 5,
                "rsi": 50,
            }
        ],
    )

    source_lines = getattr(result, f"{line_side}_lines")

    assert len(source_lines) == 1
    assert source_lines[0]["is_flipped_line"] is False
    assert len(UsdJpyM5LineOrderStrategy().build_candidates(result, 160.0)) == 1
    assert (
        len(UsdJpyM5BreakoutLineOrderStrategy().build_candidates(result, 160.0))
        == 1
    )


@pytest.mark.unit
def test_line_strength_keeps_genuinely_flipped_opposite_side_out_of_candidates():
    result = _opposite_side_line_result(
        1,
        [
            {
                "latest_time_jp": time,
                "latest_body_peak_price": price,
                "direction": direction,
                "peak_strength": 5,
                "rsi": 50,
            }
            for time, price, direction in (
                ("2026/08/28 11:58:00", 159.900, 1),
                ("2026/08/28 11:57:00", 159.905, -1),
                ("2026/08/28 11:56:00", 159.910, -1),
            )
        ],
    )

    assert len(result.lower_lines) == 1
    assert result.lower_lines[0]["is_flipped_line"] is True
    assert UsdJpyM5LineOrderStrategy().build_candidates(result, 160.0) == []
    assert UsdJpyM5BreakoutLineOrderStrategy().build_candidates(result, 160.0) == []


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


@pytest.mark.characterization
@pytest.mark.parametrize("pair_name", ["USD_JPY", "EUR_USD", "AUD_USD"])
@pytest.mark.parametrize("granularity", ["M5", "M30", "H1"])
def test_domain_peaks_match_legacy_facade_for_peak_and_skip_results(candle_frame, pair_name, granularity):
    from fGeneric import currency_pair

    pair = currency_pair(pair_name)
    frame = candle_frame.assign(body=candle_frame["close"] - candle_frame["open"])
    legacy = _LegacyPeaksClass(frame, granularity, 150.30, pair)
    domain = DomainPeaksClass(frame, granularity, 150.30, pair)

    assert domain.peaks_original == legacy.peaks_original
    assert domain.skipped_peaks == legacy.skipped_peaks
    assert domain.skipped_peaks_hard == legacy.skipped_peaks_hard


@pytest.mark.contract
def test_domain_recent_peaks_are_relative_to_analysis_frame_not_wall_clock(candle_frame):
    frame = candle_frame.assign(body=candle_frame["close"] - candle_frame["open"])
    domain = DomainPeaksClass(frame, "M5", 150.30)
    newest = frame.iloc[0]["time_jp"]

    assert newest == "2026/01/02 00:25:00"
    assert all(peak["latest_time_jp"] >= "2026/01/01 23:25:00" for peak in domain.peaks_latest)


@pytest.mark.characterization
@pytest.mark.parametrize(
    "target_peak, expected",
    [
        ({"direction": 1, "peak": 150.02}, True),
        ({"direction": 1, "peak": 149.90}, False),
        ({"direction": -1, "peak": 149.71}, True),
        ({"direction": -1, "peak": 150.10}, False),
    ],
)
def test_domain_peak_group_judgement_matches_legacy(target_peak, expected):
    peaks = [{"peak": 150.0}, {"peak": 149.98}, {"peak": 149.70}]

    assert judge_peak_is_belong_peak_group(peaks, target_peak) is expected
    assert judge_peak_is_belong_peak_group(peaks, target_peak) == _legacy_judge_peak_is_belong_peak_group(peaks, target_peak)


@pytest.mark.characterization
@pytest.mark.parametrize("pair_name", ["USD_JPY", "EUR_USD", "AUD_USD"])
def test_domain_line_grouper_matches_legacy_price_band_grouping(pair_name):
    from fGeneric import currency_pair
    from fLineAnalysis import _LegacyLineStrengthCal

    peaks = [
        {"latest_body_peak_price": 150.050, "latest_time_jp": "2026/01/02 00:20:00", "direction": 1, "peak_strength": 5, "rsi": 55},
        {"latest_body_peak_price": 150.035, "latest_time_jp": "2026/01/02 00:15:00", "direction": -1, "peak_strength": 2, "rsi": 50},
        {"latest_body_peak_price": 149.900, "latest_time_jp": "2026/01/02 00:10:00", "direction": -1, "peak_strength": 8, "rsi": None},
    ]
    legacy = object.__new__(_LegacyLineStrengthCal)
    legacy.p = currency_pair(pair_name)
    grouper = LineGrouper(pair_name)

    assert grouper.make_same_price_group(peaks, 1, 150.0, threshold=3) == legacy.make_same_price_group(peaks, 1, 150.0, threshold=3)


@pytest.mark.characterization
@pytest.mark.parametrize(
    ("pair_name", "foot", "window"),
    [
        ("USD_JPY", "m5", 60),
        ("USD_JPY", "m5", 30),
        ("USD_JPY", "h1", 65),
        ("USD_JPY", "h1", 30),
        ("EUR_USD", "m5", 60),
        ("EUR_USD", "m5", 30),
        ("EUR_USD", "h1", 65),
        ("EUR_USD", "h1", 30),
        ("AUD_USD", "m5", 60),
        ("AUD_USD", "m5", 30),
        ("AUD_USD", "h1", 65),
        ("AUD_USD", "h1", 30),
    ],
)
def test_domain_line_strength_calculator_matches_legacy_line_class(pair_name, foot, window, analysis_frame_store):
    import classCandleAnalysis
    import fLineAnalysis

    frames = analysis_frame_store[pair_name]
    current_price = {"USD_JPY": 150.77, "EUR_USD": 1.1099, "AUD_USD": 0.7065}[pair_name]
    candle = classCandleAnalysis.candleAnalysis(
        None,
        pair_name,
        0,
        m5_df_r=frames["M5"].copy(),
        h1_df_r=frames["H1"].copy(),
        m30_df_r=frames["M30"].copy(),
        current_price=current_price,
    )
    legacy = fLineAnalysis.LineStrengthCal(candle, foot, window)
    peaks = candle.peaks_class.peaks_original if foot == "m5" else candle.peaks_class_hour.peaks_original
    frame = candle.d5_df_r[1:] if foot == "m5" else candle.h1_df_r
    domain = LineStrengthCalculator(pair_name).calculate(
        foot=foot,
        peaks=peaks,
        frame=frame,
        current_price=current_price,
        current_time=candle.d5_df_r.iloc[0]["time_jp"],
        time_before_foot_count=window,
    )

    for attribute in ("upper_lines", "lower_lines", "tp_lines", "lc_lines", "all_lines"):
        assert getattr(domain, attribute) == getattr(legacy, attribute)
        for line_class in (domain, legacy):
            assert all(
                isinstance(line.get("is_flipped_line"), bool)
                for line in getattr(line_class, attribute)
            )


@pytest.mark.characterization
def test_line_candidate_coordinator_adds_context_and_removes_near_candidates():
    peak = {"direction": 1, "count": 2, "gap": 0.1, "latest_time_jp": "2026/01/02 06:00:00", "peak_strength": 5, "latest_body_peak_price": 150.1, "rsi": 55}
    analysis = type("Analysis", (), {"pair": "USD_JPY", "peaks_class": type("Peaks", (), {"peaks_original": [peak, peak]})(), "peaks_class_hour": type("Peaks", (), {"peaks_original": [peak, peak]})()})()
    coordinator = LineCandidateCoordinator(analysis, LineStrategyProfileUsdJpy())
    candidates = [
        {"direction": 1, "line_strategy": "m5", "line_price": 150.10, "distance_pips": 2, "timeframe": "m5"},
        {"direction": 1, "line_strategy": "m5", "line_price": 150.12, "distance_pips": 4, "timeframe": "m5"},
    ]

    info = coordinator.attach_candidate_decision_context(candidates[0], "2026/01/02 06:00:00", "limit")

    assert info["direction"] == 1
    assert candidates[0]["session_name"] == "morning"
    assert coordinator.remove_near_candidates(candidates) == [candidates[0]]


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
