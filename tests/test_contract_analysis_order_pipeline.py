import json
from pathlib import Path

import pytest

import classCandleAnalysis
import fAnalysis_order_Main
from ogami_oanda.adapters.legacy.order_dict import order_plan_to_legacy_dict
from ogami_oanda.application.services.line_candidate_context_builder import (
    build_line_candidate_context,
)
from ogami_oanda.application.services.market_analysis_service import (
    MarketAnalysisService,
)
from ogami_oanda.application.services.order_planner import OrderPlanner
from ogami_oanda.strategy.line import LineCandidateBuilder
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
