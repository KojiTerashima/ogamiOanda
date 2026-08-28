import json
from pathlib import Path

import pandas as pd
import pytest

from ogami_oanda.application.services.line_candidate_context_builder import (
    build_line_candidate_context,
)
from ogami_oanda.application.services.market_analysis_service import (
    MarketAnalysisService,
)
from ogami_oanda.application.services.portfolio import ActiveOrder, Portfolio
from ogami_oanda.domain.analysis.peaks import PeaksClass
from ogami_oanda.domain.market.currency_pair import currency_pair
from ogami_oanda.domain.orders.models import Direction
from ogami_oanda.strategy.line import LineCandidateBuilder
from ogami_oanda.strategy.line.builder import (
    CandidateBuildResult,
    CandidateDiagnostics,
)
from tests.fakes import FakeMarketData
from tests.test_characterization_analysis_oracle import _candidate_summary


def _frame():
    times = pd.date_range("2026-01-02 01:00:00", periods=40, freq="-5min")
    close = [150 + index * 0.01 for index in range(40)]
    return pd.DataFrame({
        "time_jp": [value.strftime("%Y/%m/%d %H:%M:%S") for value in times],
        "open": close,
        "close": [value + 0.005 for value in close],
        "high": [value + 0.02 for value in close],
        "low": [value - 0.02 for value in close],
        "inner_high": [value + 0.005 for value in close],
        "inner_low": close,
    })


@pytest.mark.contract
def test_market_analysis_builds_intents_from_validated_market_frames():
    frame = _frame()
    market_data = FakeMarketData({("USD_JPY", granularity): frame for granularity in ("M5", "H1", "M30", "S5")}, {"USD_JPY": 150.4})
    service = MarketAnalysisService(
        market_data,
        lambda context, price: [{"direction": 1, "target_price": 150.3, "line_strategy": "test", "lc_pips": 10, "tp_pips": 20, "order_timeout_min": 15}],
    )

    result = service.analyze("USD_JPY", "2026/01/02 01:00:00")

    assert len(result.intents) == 1
    assert result.intents[0].direction is Direction.BUY
    assert result.intents[0].trade_timeout_min == 240
    assert result.intents[0].lc_change == ()
    assert result.intents[0].metadata["line_strategy"] == "test"
    assert set(result.peaks) == {"M5", "H1", "M30"}


@pytest.mark.contract
def test_market_analysis_preserves_candidate_position_management_fields():
    frame = _frame()
    market_data = FakeMarketData(
        {("USD_JPY", granularity): frame for granularity in ("M5", "H1", "M30", "S5")},
        {"USD_JPY": 150.4},
    )
    lc_change = [{"exe": True, "time_after": 60, "trigger": 0.03, "ensure": 0.01}]
    service = MarketAnalysisService(
        market_data,
        lambda context, price: [
            {
                "direction": -1,
                "target_price": 150.5,
                "trade_timeout_min": "90",
                "lc_change": lc_change,
            }
        ],
    )

    intent = service.analyze("USD_JPY", "2026/01/02 01:00:00").intents[0]
    lc_change[0]["trigger"] = 99

    assert intent.trade_timeout_min == 90
    assert isinstance(intent.trade_timeout_min, int)
    assert intent.lc_change == (
        {"exe": True, "time_after": 60, "trigger": 0.03, "ensure": 0.01},
    )
    assert isinstance(intent.lc_change, tuple)


@pytest.mark.contract
def test_market_analysis_excludes_matching_active_line_orders():
    frame = _frame()
    market_data = FakeMarketData({("USD_JPY", granularity): frame for granularity in ("M5", "H1", "M30", "S5")}, {"USD_JPY": 150.4})
    portfolio = Portfolio(currency_pair("USD_JPY"), (ActiveOrder("existing", 1, 150.3, "line", "test"),))
    service = MarketAnalysisService(market_data, lambda context, price: [{"direction": 1, "target_price": 150.3, "line_strategy": "test"}], portfolio)

    assert service.analyze("USD_JPY", "2026/01/02 01:00:00").intents == ()


@pytest.mark.contract
def test_market_analysis_reports_similar_active_order_candidate_rejection():
    frame = _frame()
    market_data = FakeMarketData(
        {
            ("USD_JPY", granularity): frame
            for granularity in ("M5", "H1", "M30", "S5")
        },
        {"USD_JPY": 150.4},
    )
    portfolio = Portfolio(
        currency_pair("USD_JPY"),
        (ActiveOrder("existing", 1, 150.3, "line", "test"),),
    )

    class DiagnosedBuilder:
        def __call__(self, _context, _price):
            raise AssertionError("diagnostic-aware build path was not used")

        def build_with_diagnostics(self, _context, _price):
            return CandidateBuildResult(
                candidates=(
                    {
                        "direction": 1,
                        "target_price": 150.3,
                        "line_strategy": "test",
                        "source": "line",
                        "order_mode": "future_resist",
                    },
                ),
                diagnostics=CandidateDiagnostics(
                    raw_counts={
                        "immediate": 0,
                        "future_resist": 1,
                        "future_break": 0,
                    },
                    selected_counts={
                        "immediate": 0,
                        "future_resist": 1,
                        "future_break": 0,
                    },
                    rejected_reasons={
                        "immediate": {},
                        "future_resist": {},
                        "future_break": {},
                    },
                ),
            )

    result = MarketAnalysisService(
        market_data,
        DiagnosedBuilder(),
        portfolio,
    ).analyze("USD_JPY", "2026/01/02 01:00:00")

    assert result.intents == ()
    assert result.candidate_diagnostics.selected_counts["future_resist"] == 0
    assert result.candidate_diagnostics.rejected_reasons["future_resist"] == {
        "similar_active_order": 1,
    }


@pytest.mark.contract
def test_market_analysis_keeps_diagnostics_optional_for_callable_builders():
    frame = _frame()
    market_data = FakeMarketData(
        {
            ("USD_JPY", granularity): frame
            for granularity in ("M5", "H1", "M30", "S5")
        },
        {"USD_JPY": 150.4},
    )
    service = MarketAnalysisService(market_data, lambda _context, _price: [])

    result = service.analyze("USD_JPY", "2026/01/02 01:00:00")

    assert result.candidate_diagnostics is None


def _candidate_builder_context(pair_name, frames, current_price, decision_time):
    pair = currency_pair(pair_name)
    peaks = {
        granularity: PeaksClass(frames[granularity], granularity, current_price, pair)
        for granularity in ("M5", "H1", "M30")
    }
    return build_line_candidate_context(pair_name, frames, peaks, current_price, decision_time)


@pytest.mark.contract
@pytest.mark.parametrize(
    ("pair_name", "snapshot_name"),
    [
        ("USD_JPY", "analysis_oracle_usd_jpy.json"),
        ("EUR_USD", "analysis_oracle_eur_usd.json"),
        ("AUD_USD", "analysis_oracle_aud_usd.json"),
    ],
)
def test_market_analysis_service_accepts_line_candidate_context_builder(pair_name, snapshot_name, analysis_frame_store):
    snapshot_path = Path(__file__).parent / "fixtures" / snapshot_name
    expected = json.loads(snapshot_path.read_text(encoding="utf-8"))
    frames = analysis_frame_store[pair_name]
    market_data = FakeMarketData(
        {(pair_name, granularity): frames[granularity] for granularity in ("M5", "H1", "M30", "S5")},
        {pair_name: expected["current_price"]},
    )
    service = MarketAnalysisService(
        market_data,
        LineCandidateBuilder(pair_name),
        candidate_context_builder=build_line_candidate_context,
    )

    result = service.analyze(pair_name, expected["decision_time"])
    expected_candidates = (
        expected["selected_immediate_candidates"]
        + expected["selected_future_resist_candidates"]
        + expected["selected_future_break_candidates"]
    )

    assert len(result.intents) == len(expected_candidates)
    for intent, candidate in zip(result.intents, expected_candidates):
        assert intent.direction.value == candidate["direction"]
        assert intent.metadata["line_strategy"] == candidate["line_strategy"]
        assert intent.metadata["line_side"] == candidate["line_side"]
        assert intent.metadata["order_mode"] == candidate["order_mode"]
        assert intent.metadata["recommended_reasons"] == candidate["recommended_reasons"]


@pytest.mark.contract
def test_market_analysis_service_enriches_line_candidates_for_order_intents(analysis_frame_store):
    snapshot_path = Path(__file__).parent / "fixtures" / "analysis_oracle_eur_usd.json"
    expected = json.loads(snapshot_path.read_text(encoding="utf-8"))
    pair_name = "EUR_USD"
    frames = analysis_frame_store[pair_name]
    market_data = FakeMarketData(
        {(pair_name, granularity): frames[granularity] for granularity in ("M5", "H1", "M30", "S5")},
        {pair_name: expected["current_price"]},
    )
    service = MarketAnalysisService(
        market_data,
        LineCandidateBuilder(pair_name),
        candidate_context_builder=build_line_candidate_context,
    )

    result = service.analyze(pair_name, expected["decision_time"])

    assert len(result.intents) == 1
    assert result.intents[0].order_type.value == "STOP"
    assert result.intents[0].target == pytest.approx(1.10905)
    assert result.intents[0].units == 166
    assert result.intents[0].priority == 8
    assert result.intents[0].name == "M5LineBreakout_lower_0_12:00"
    assert result.intents[0].order_timeout_min == 45
    assert result.intents[0].metadata["lc_pips"] == 7.5
    assert result.intents[0].metadata["tp_pips"] == 14.1
    assert result.intents[0].stop_loss == pytest.approx(0.0005)
    assert result.intents[0].take_profit == pytest.approx(0.0005)
    assert result.intents[0].metadata["path_tp_adjusted"] is True
    assert result.intents[0].metadata["path_tp_original_pips"] == pytest.approx(
        14.1
    )
    assert result.intents[0].metadata["path_lc_original_pips"] == pytest.approx(
        7.5
    )
    assert result.intents[0].metadata["units_multiplier"] == 0.25
    assert result.intents[0].metadata["session_name"] == "day"
    assert result.intents[0].metadata["session_rr"] is None
    assert result.intents[0].metadata["line_timeframe"] == "m5"
    assert result.intents[0].metadata["line_entry_type"] == "breakout"


@pytest.mark.contract
@pytest.mark.parametrize(
    ("pair_name", "snapshot_name"),
    [
        ("USD_JPY", "analysis_oracle_usd_jpy.json"),
        ("EUR_USD", "analysis_oracle_eur_usd.json"),
        ("AUD_USD", "analysis_oracle_aud_usd.json"),
    ],
)
def test_line_candidate_builder_matches_characterized_selected_candidates(pair_name, snapshot_name, analysis_frame_store):
    snapshot_path = Path(__file__).parent / "fixtures" / snapshot_name
    expected = json.loads(snapshot_path.read_text(encoding="utf-8"))
    builder = LineCandidateBuilder(pair_name)
    context = _candidate_builder_context(
        pair_name,
        analysis_frame_store[pair_name],
        expected["current_price"],
        expected["decision_time"],
    )

    raw = builder.build_raw_candidates(context, float(expected["current_price"]))
    actual = builder.select_candidates(raw, context)

    assert _candidate_summary(raw["immediate"]) == expected["immediate_candidates"]
    assert _candidate_summary(raw["future_resist"]) == expected["future_resist_candidates"]
    assert _candidate_summary(raw["future_break"]) == expected["future_break_candidates"]

    assert _candidate_summary(actual) == (
        expected["selected_immediate_candidates"]
        + expected["selected_future_resist_candidates"]
        + expected["selected_future_break_candidates"]
    )


@pytest.mark.contract
def test_line_candidate_builder_reports_mode_counts_and_rejection_reasons(
    analysis_frame_store,
):
    snapshot_path = Path(__file__).parent / "fixtures" / "analysis_oracle_usd_jpy.json"
    expected = json.loads(snapshot_path.read_text(encoding="utf-8"))
    current_price = float(expected["current_price"])
    builder = LineCandidateBuilder("USD_JPY")
    context = _candidate_builder_context(
        "USD_JPY",
        analysis_frame_store["USD_JPY"],
        current_price,
        expected["decision_time"],
    )

    result = builder.build_with_diagnostics(context, current_price)

    assert result.diagnostics.raw_counts == {
        "immediate": 8,
        "future_resist": 8,
        "future_break": 8,
    }
    assert result.diagnostics.selected_counts == {
        "immediate": 0,
        "future_resist": 0,
        "future_break": 0,
    }
    assert result.diagnostics.rejected_reasons == {
        "immediate": {"immediate_conditions_not_met": 8},
        "future_resist": {"top7_conditions_not_met": 8},
        "future_break": {"top7_conditions_not_met": 8},
    }
    assert list(result.candidates) == builder(context, current_price)
    for mode in ("immediate", "future_resist", "future_break"):
        assert result.diagnostics.raw_counts[mode] == (
            result.diagnostics.selected_counts[mode]
            + sum(result.diagnostics.rejected_reasons[mode].values())
        )


@pytest.mark.contract
def test_line_candidate_builder_reports_session_policy_rejection(
    analysis_frame_store,
):
    snapshot_path = Path(__file__).parent / "fixtures" / "analysis_oracle_eur_usd.json"
    expected = json.loads(snapshot_path.read_text(encoding="utf-8"))
    current_price = float(expected["current_price"])
    builder = LineCandidateBuilder("EUR_USD")
    builder.profile.session_policies = {
        **builder.profile.session_policies,
        "day": {
            **builder.profile.session_policies["day"],
            "order_permission": False,
        },
    }
    context = _candidate_builder_context(
        "EUR_USD",
        analysis_frame_store["EUR_USD"],
        current_price,
        expected["decision_time"],
    )

    result = builder.build_with_diagnostics(context, current_price)

    assert result.diagnostics.selected_counts["future_break"] == 0
    assert result.diagnostics.rejected_reasons["future_break"] == {
        "recommendation_conditions_not_met": 8,
        "session_order_permission_false": 1,
    }
    assert result.diagnostics.raw_counts["future_break"] == 9
