import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import classCandleAnalysis
from classOrderCreate import Order
import fAnalysis_order_Main
import fLineAnalysis
import fLineStrategyUsdJpy
from ogami_oanda.adapters.oanda.mappers import broker_request_to_oanda
from ogami_oanda.adapters.legacy.order_dict import order_plan_to_legacy_dict
from ogami_oanda.application.services.line_candidate_context_builder import (
    build_line_candidate_context,
)
from ogami_oanda.application.services.market_analysis_service import (
    MarketAnalysisService,
)
from ogami_oanda.application.services.order_planner import OrderPlanner
from ogami_oanda.domain.market.currency_pair import currency_pair
from ogami_oanda.strategy.line import (
    LineCandidateBuilder,
    LineCandidateCoordinator,
    LineStrategyProfileUsdJpy,
    UsdJpyM5BreakoutLineOrderStrategy,
)
from tests.fakes import FakeMarketData
from tests.test_characterization_analysis_oracle import _order_summary, _snapshot_value


@pytest.mark.contract
@pytest.mark.parametrize(
    ("pair_name", "snapshot_name"),
    [
        ("USD_JPY", "analysis_oracle_usd_jpy.json"),
        ("EUR_USD", "analysis_oracle_eur_usd.json"),
        ("AUD_USD", "analysis_oracle_aud_usd.json"),
    ],
)
def test_market_analysis_order_pipeline_matches_legacy_order_plans(pair_name, snapshot_name, analysis_frame_store):
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
    planner = OrderPlanner()
    actual = [
        order_plan_to_legacy_dict(
            planner.plan(
                intent,
                result.order_context,
            )
        )
        for intent in result.intents
    ]
    expected_plans = [order["plan"] | {"for_api_json": {"order": order["payload"]}} for order in expected["legacy_orders"]]

    assert _snapshot_value(actual) == _snapshot_value(expected_plans)


@pytest.mark.contract
@pytest.mark.parametrize(
    ("pair_name", "snapshot_name"),
    [
        ("USD_JPY", "analysis_oracle_usd_jpy.json"),
        ("EUR_USD", "analysis_oracle_eur_usd.json"),
        ("AUD_USD", "analysis_oracle_aud_usd.json"),
    ],
)
def test_root_analysis_facade_matches_legacy_order_snapshot(pair_name, snapshot_name, analysis_frame_store):
    snapshot_path = Path(__file__).parent / "fixtures" / snapshot_name
    expected = json.loads(snapshot_path.read_text(encoding="utf-8"))
    frames = analysis_frame_store[pair_name]
    candle = classCandleAnalysis.candleAnalysis(
        None,
        pair_name,
        0,
        m5_df_r=frames["M5"].copy(),
        h1_df_r=frames["H1"].copy(),
        m30_df_r=frames["M30"].copy(),
        current_price=expected["current_price"],
    )

    actual = fAnalysis_order_Main.wrap_all_analysis(candle, None, "inspection")

    assert actual.take_position_flag is bool(expected["legacy_orders"])
    assert _order_summary(actual.exe_order_classes) == expected["legacy_orders"]


class _LegacyCandleMeta:
    @staticmethod
    def cal_move_ave(_times):
        return 0


class _LegacyCandle:
    candle_meta_class = _LegacyCandleMeta()


def _usd_top7_candidate(
    *,
    side,
    entry_type,
    count,
    strength,
    h1_distance,
    current_rsi,
    peak_rsi,
    session_hour=12,
):
    peak_direction = 1 if side == "upper" else -1
    direction = (
        peak_direction
        if entry_type == "breakout"
        else -peak_direction
    )
    return {
        "timeframe": "m5",
        "line_side": side,
        "direction": direction,
        "line_strategy": f"m5_{entry_type}_peakdir_allcount",
        "strategy": SimpleNamespace(entry_type=entry_type),
        "latest_peak_dir": peak_direction,
        "latest_peak_rsi": peak_rsi,
        "previous_peak_rsi": peak_rsi,
        "session_hour": session_hour,
        "line": {
            "count": count,
            "total_strength": strength,
            "core_count": 1,
            "core_total_strength": min(strength, 5),
        },
        "h1_context": {
            "h1_nearest_distance_pips": h1_distance,
            "h1_nearest_side": side,
            "h1_blocks_trade_direction": True,
            "h1_path_ahead_1_distance_pips": h1_distance,
            "h1_path_ahead_1_total_strength": 8,
        },
        "rsi_info": {"rsi_1": current_rsi},
        "latest_peak_info": {"direction": peak_direction},
    }


@pytest.mark.contract
@pytest.mark.parametrize(
    "profile_factory",
    (LineStrategyProfileUsdJpy, fLineStrategyUsdJpy.LineStrategyProfileUsdJpy),
)
@pytest.mark.parametrize("side", ("upper", "lower"))
def test_usd_jpy_future_reversal_uses_top7_for_both_sides(
    profile_factory,
    side,
):
    profile = profile_factory()
    candidate = _usd_top7_candidate(
        side=side,
        entry_type="reversal",
        count=1,
        strength=5,
        h1_distance=8,
        current_rsi=55,
        peak_rsi=55,
    )

    reasons = profile.future_resist_recommended_reasons(
        candidate,
        candidate["rsi_info"],
        candidate["latest_peak_info"],
    )

    assert reasons == [
        f"Top2 {side} reversal c1 str0-5 H1same6-10 RSI50-60"
    ]


@pytest.mark.contract
@pytest.mark.parametrize(
    "profile_factory",
    (LineStrategyProfileUsdJpy, fLineStrategyUsdJpy.LineStrategyProfileUsdJpy),
)
@pytest.mark.parametrize("side", ("upper", "lower"))
def test_usd_jpy_future_breakout_uses_top7_for_both_sides(
    profile_factory,
    side,
):
    profile = profile_factory()
    candidate = _usd_top7_candidate(
        side=side,
        entry_type="breakout",
        count=1,
        strength=5,
        h1_distance=4,
        current_rsi=45,
        peak_rsi=45,
    )

    reasons = profile.future_break_recommended_reasons(
        candidate,
        candidate["rsi_info"],
        candidate["latest_peak_info"],
    )

    assert reasons == [
        f"Top6 {side} breakout c1 str0-5 H1same3-6 RSI40-50"
    ]


@pytest.mark.contract
@pytest.mark.parametrize(
    "profile_factory",
    (LineStrategyProfileUsdJpy, fLineStrategyUsdJpy.LineStrategyProfileUsdJpy),
)
def test_usd_jpy_future_rejects_top10_only_candidate(profile_factory):
    profile = profile_factory()
    candidate = _usd_top7_candidate(
        side="upper",
        entry_type="reversal",
        count=3,
        strength=6,
        h1_distance=8,
        current_rsi=65,
        peak_rsi=70,
        session_hour=7,
    )

    reasons = profile.future_resist_recommended_reasons(
        candidate,
        candidate["rsi_info"],
        candidate["latest_peak_info"],
    )

    assert reasons == []


def _accepted_pair_candidates(pair_name, current_price):
    pair = currency_pair(pair_name)
    builder = LineCandidateBuilder(pair_name)
    selected = []
    for index, (line_side, direction) in enumerate(
        (("upper", 1), ("lower", -1))
    ):
        strategy = UsdJpyM5BreakoutLineOrderStrategy(builder.profile)
        strategy.pair = pair_name
        target_price = pair.round_price(
            current_price + direction * pair.pips_to_price(5)
        )
        line_price = pair.round_price(
            target_price
            - direction * pair.pips_to_price(strategy.entry_offset_pips)
        )
        selected.append(
            {
                "timeframe": "m5",
                "line_side": line_side,
                "direction": direction,
                "line_index": index,
                "line_price": line_price,
                "target_price": target_price,
                "line_strategy": strategy.line_strategy,
                "distance_pips": 5,
                "strategy": strategy,
                "line": {
                    "median_price": line_price,
                    "total_strength": 8 - index,
                    "count": 1,
                    "ave_strength": 8 - index,
                    "core_median_price": line_price,
                    "core_count": 1,
                    "core_total_strength": 8 - index,
                    "is_flipped_line": False,
                },
                "order_mode": "future_break",
                "recommended_reasons": [f"{pair_name} accepted {line_side}"],
                "memo": f"positive {pair_name} {line_side}",
            }
        )
    return builder.enrich_candidates(selected, current_price)


@pytest.mark.contract
@pytest.mark.parametrize(
    (
        "pair_name",
        "current_price",
        "direction",
        "line_side",
        "distance_pips",
        "line_strength",
        "core_strength",
        "path_distance",
        "peak_rsi",
        "expected_reason",
    ),
    [
        (
            "USD_JPY",
            150.0,
            1,
            "upper",
            5,
            5,
            5,
            4,
            50,
            "Top6 upper breakout c1 str0-5 H1same3-6 RSI40-50",
        ),
        (
            "EUR_USD",
            1.1,
            -1,
            "lower",
            8.5,
            6,
            6,
            20,
            50,
            "EUR Top8 lower 8-10p lineStr5-8",
        ),
        (
            "AUD_USD",
            0.7,
            -1,
            "lower",
            5,
            8,
            12,
            4,
            70,
            "AUD 1Y Top4 path3-6 coreStr10-15",
        ),
    ],
)
def test_three_pair_real_strategy_selects_positive_candidate(
    pair_name,
    current_price,
    direction,
    line_side,
    distance_pips,
    line_strength,
    core_strength,
    path_distance,
    peak_rsi,
    expected_reason,
):
    builder = LineCandidateBuilder(pair_name)
    pair = currency_pair(pair_name)
    strategy = UsdJpyM5BreakoutLineOrderStrategy(builder.profile)
    strategy.pair = pair_name
    target_price = pair.round_price(
        current_price + direction * pair.pips_to_price(distance_pips)
    )
    line_price = pair.round_price(
        target_price
        - direction * pair.pips_to_price(strategy.entry_offset_pips)
    )
    candidate = {
        "timeframe": "m5",
        "line_side": line_side,
        "direction": direction,
        "line_index": 0,
        "line_price": line_price,
        "target_price": target_price,
        "line_strategy": strategy.line_strategy,
        "distance_pips": distance_pips,
        "strategy": strategy,
        "line": {
            "median_price": line_price,
            "total_strength": line_strength,
            "count": 1,
            "ave_strength": line_strength,
            "core_median_price": line_price,
            "core_count": 1,
            "core_total_strength": core_strength,
            "is_flipped_line": False,
        },
        "h1_context": {
            "h1_path_ahead_1_distance_pips": path_distance,
            "h1_nearest_distance_pips": path_distance,
            "h1_nearest_side": line_side,
            "h1_blocks_trade_direction": True,
        },
    }
    peaks = SimpleNamespace(
        peaks_original=[
            {
                "direction": direction,
                "count": 2,
                "gap": distance_pips,
                "latest_time_jp": "2026/01/02 12:00:00",
                "peak_strength": 5,
                "latest_body_peak_price": current_price,
                "rsi": peak_rsi,
            },
            {
                "direction": -direction,
                "count": 2,
                "gap": distance_pips,
                "latest_time_jp": "2026/01/02 11:55:00",
                "peak_strength": 5,
                "latest_body_peak_price": current_price,
                "rsi": 50,
            },
        ]
    )
    context = {
        "peaks": {"M5": peaks, "H1": peaks},
        "decision_time": "2026/01/02 12:00:00",
        "rsi_info": {"rsi_1": 50},
    }

    selected = builder.select_candidates(
        {
            "immediate": [],
            "future_resist": [],
            "future_break": [candidate],
        },
        context,
    )

    assert len(selected) == 1
    assert expected_reason in selected[0]["recommended_reasons"]
    assert builder.enrich_candidates(selected, current_price)[0]["units"] > 0


@pytest.mark.contract
@pytest.mark.parametrize(
    ("pair_name", "current_price"),
    [
        ("USD_JPY", 150.77),
        ("EUR_USD", 1.1099),
        ("AUD_USD", 0.7065),
    ],
)
def test_accepted_pair_candidates_preserve_intent_plan_and_payload_order(
    pair_name,
    current_price,
    analysis_frame_store,
):
    frames = analysis_frame_store[pair_name]
    market_data = FakeMarketData(
        {
            (pair_name, granularity): frames[granularity]
            for granularity in ("M5", "H1", "M30", "S5")
        },
        {pair_name: current_price},
    )
    service = MarketAnalysisService(
        market_data,
        lambda _context, price: _accepted_pair_candidates(pair_name, price),
    )

    result = service.analyze(pair_name, "2026/01/02 11:55:00")
    plans = [
        OrderPlanner().plan(intent, result.order_context)
        for intent in result.intents
    ]

    assert [intent.metadata["line_side"] for intent in result.intents] == [
        "upper",
        "lower",
    ]
    assert [
        intent.metadata["recommended_reasons"] for intent in result.intents
    ] == [
        [f"{pair_name} accepted upper"],
        [f"{pair_name} accepted lower"],
    ]

    pair = currency_pair(pair_name)
    for intent, plan in zip(result.intents, plans):
        legacy = Order(
            {
                "name": intent.name,
                "current_price": current_price,
                "target": plan.target_price,
                "direction": intent.direction.value,
                "type": intent.order_type.value,
                "tp": pair.pips_to_price(14.1),
                "lc": pair.pips_to_price(7.5),
                "units": intent.units,
                "priority": intent.priority,
                "decision_time": result.order_context.decision_time,
                "pair": pair_name,
                "order_timeout_min": intent.order_timeout_min,
                "lc_change": [],
                "candle_analysis_class": _LegacyCandle(),
            }
        )
        legacy_plan = legacy.exe_order_plan

        assert plan.target_price == legacy_plan["target_price"]
        assert plan.take_profit_price == legacy_plan["tp_price"]
        assert plan.stop_loss_price == legacy_plan["lc_price"]
        assert order_plan_to_legacy_dict(plan)["for_api_json"] == legacy_plan[
            "for_api_json"
        ]
        wire_order = broker_request_to_oanda(plan.broker_request)["order"]
        assert wire_order == {
            **legacy_plan["for_api_json"]["order"],
            "timeInForce": "GTC",
        }


@pytest.mark.contract
def test_root_analysis_facade_adapts_legacy_risk_setting(
    monkeypatch,
    analysis_frame_store,
):
    pair_name = "EUR_USD"
    expected = json.loads(
        (
            Path(__file__).parent
            / "fixtures"
            / "analysis_oracle_eur_usd.json"
        ).read_text(encoding="utf-8")
    )
    frames = analysis_frame_store[pair_name]
    monkeypatch.setitem(fLineAnalysis.tk.setting_json, "l_units", 1000)
    candle = classCandleAnalysis.candleAnalysis(
        None,
        pair_name,
        0,
        m5_df_r=frames["M5"].copy(),
        h1_df_r=frames["H1"].copy(),
        m30_df_r=frames["M30"].copy(),
        current_price=expected["current_price"],
    )

    actual = fAnalysis_order_Main.wrap_all_analysis(
        candle,
        None,
        "inspection",
    )

    assert actual.exe_order_classes[0].exe_order_plan["units"] == 333
    assert (
        actual.exe_order_classes[0]
        .exe_order_plan["for_api_json"]["order"]["units"]
        == "-333"
    )


@pytest.mark.contract
def test_root_analysis_public_facade_does_not_construct_legacy_analysis(
    monkeypatch,
    analysis_frame_store,
):
    class _LegacyMustNotRun:
        def __init__(self, *_args, **_kwargs):
            raise AssertionError("legacy analysis implementation was called")

    calls = []
    src_analyze = MarketAnalysisService.analyze

    def tracked_analyze(self, pair, decision_time, **kwargs):
        calls.append((pair, decision_time))
        return src_analyze(self, pair, decision_time, **kwargs)

    pair_name = "EUR_USD"
    frames = analysis_frame_store[pair_name]
    monkeypatch.setattr(
        fLineAnalysis,
        "_LegacyMainAnalysis",
        _LegacyMustNotRun,
    )
    monkeypatch.setattr(MarketAnalysisService, "analyze", tracked_analyze)
    candle = classCandleAnalysis.candleAnalysis(
        None,
        pair_name,
        0,
        m5_df_r=frames["M5"].copy(),
        h1_df_r=frames["H1"].copy(),
        m30_df_r=frames["M30"].copy(),
        current_price=1.1099,
    )

    actual = fAnalysis_order_Main.wrap_all_analysis(
        candle,
        None,
        "inspection",
    )

    assert actual.take_position_flag is True
    assert len(actual.exe_order_classes) == 1
    assert calls == [("EUR_USD", "2026/01/02 12:00:00")]


@pytest.mark.contract
def test_public_line_order_coordinator_creates_src_plan_legacy_views(
    monkeypatch,
):
    pair_name = "EUR_USD"
    pair = currency_pair(pair_name)
    profile = fLineAnalysis.line_strategy_profile(pair_name)
    strategy = UsdJpyM5BreakoutLineOrderStrategy(profile)
    strategy.pair = pair_name
    current_price = 1.1
    target_price = 1.0995
    line_price = pair.round_price(
        target_price + pair.pips_to_price(strategy.entry_offset_pips)
    )
    candidate = {
        "timeframe": "m5",
        "line_side": "lower",
        "direction": -1,
        "line_index": 0,
        "line_price": line_price,
        "target_price": target_price,
        "line_strategy": strategy.line_strategy,
        "distance_pips": 5,
        "strategy": strategy,
        "line": {
            "median_price": line_price,
            "total_strength": 8,
            "count": 1,
            "ave_strength": 8,
            "core_median_price": line_price,
            "core_count": 1,
            "core_total_strength": 8,
            "is_flipped_line": False,
        },
        "recommended_reasons": ["accepted by contract"],
        "memo": "src facade",
    }

    class _Analysis:
        pair = pair_name
        each_pair_line_strategy_profile = profile

        def __init__(self):
            self.added = []

        @staticmethod
        def has_similar_order(*_args, **_kwargs):
            return False

        def add_order_to_this_class(self, orders):
            self.added.extend(orders)

    analysis = _Analysis()
    monkeypatch.setattr(
        fLineAnalysis.OCreate,
        "Order",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("legacy Order must not be constructed")
        ),
    )

    orders = fLineAnalysis.LineOrderCoordinator(
        analysis
    ).create_orders_from_candidates(
        [candidate],
        current_price,
        "2026/01/02 12:00:00",
        {"rsi_1": 50},
        "future_break",
    )

    assert analysis.added == orders
    assert len(orders) == 1
    assert orders[0].exe_order_plan["units"] == 166
    assert orders[0].exe_order_plan["type"] == "STOP"
    assert orders[0].exe_order_plan["for_api_json"]["order"]["units"] == "-166"


@pytest.mark.contract
def test_root_line_order_coordinator_delegates_candidate_build_to_strategy(
    monkeypatch,
):
    calls = []
    src_build = LineCandidateCoordinator.build_line_candidates

    def tracked_build(self, strategy_lines, current_price, **kwargs):
        calls.append((strategy_lines, current_price, kwargs))
        return src_build(self, strategy_lines, current_price, **kwargs)

    monkeypatch.setattr(
        LineCandidateCoordinator,
        "build_line_candidates",
        tracked_build,
    )
    analysis = SimpleNamespace(
        pair="USD_JPY",
        each_pair_line_strategy_profile=LineStrategyProfileUsdJpy(),
    )

    actual = fLineAnalysis.LineOrderCoordinator(
        analysis
    ).build_line_candidates([], 150.0)

    assert actual == []
    assert calls == [
        (
            [],
            150.0,
            {
                "h1_line_class": None,
                "m5_line_class": None,
                "order_mode": "limit",
            },
        )
    ]
