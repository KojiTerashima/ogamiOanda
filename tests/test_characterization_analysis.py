import pytest

from classCandlePeaks import (
    PeaksClass,
    _legacy_judge_peak_is_belong_peak_group,
    _LegacyPeaksClass,
)
from fLineAnalysis import LineOrderCoordinator
from ogami_oanda.domain.analysis.lines import LineGrouper
from ogami_oanda.domain.analysis.peaks import (
    PeaksClass as DomainPeaksClass,
)
from ogami_oanda.domain.analysis.peaks import (
    judge_peak_is_belong_peak_group,
)
from ogami_oanda.strategy.line import (
    LineCandidateCoordinator,
    LineStrategyProfileUsdJpy,
)


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
