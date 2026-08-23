from dataclasses import dataclass, field

import pytest

from classOrderCreate import Order
from ogami_oanda.adapters.oanda.mappers import broker_request_to_oanda
from ogami_oanda.adapters.legacy.order_dict import order_plan_to_legacy_dict
from ogami_oanda.application.services.order_planner import OrderPlanner
from ogami_oanda.domain.orders.models import (
    Direction,
    OrderContext,
    OrderIntent,
    OrderType,
)


@dataclass
class _CandleMeta:
    def cal_move_ave(self, times):
        return 0.12


@dataclass
class _CandleAnalysis:
    candle_meta_class: _CandleMeta = field(default_factory=_CandleMeta)


@pytest.mark.contract
@pytest.mark.parametrize(
    ("pair", "current_price", "order_type", "direction", "target", "tp", "lc"),
    [
        ("USD_JPY", 150.0, OrderType.STOP, Direction.BUY, 0.1, 0.2, 0.1),
        ("EUR_USD", 1.1, OrderType.LIMIT, Direction.SELL, 0.001, 0.002, 0.001),
        ("AUD_USD", 0.7, OrderType.MARKET, Direction.BUY, 0.005, 0.003, 0.002),
    ],
)
def test_order_planner_matches_legacy_prices_and_preserves_historical_payload_view(
    pair,
    current_price,
    order_type,
    direction,
    target,
    tp,
    lc,
):
    legacy_order = Order(
        {
            "name": "baseline",
            "current_price": current_price,
            "target": target,
            "direction": direction.value,
            "type": order_type.value,
            "tp": tp,
            "lc": lc,
            "units": 10000,
            "priority": 5,
            "decision_time": "2026/01/02 03:04:05",
            "pair": pair,
            "order_timeout_min": 45,
            "lc_change": [],
            "candle_analysis_class": _CandleAnalysis(),
        }
    )
    intent = OrderIntent(
        pair=pair,
        direction=direction,
        order_type=order_type,
        target=target,
        target_is_price=False,
        take_profit=tp,
        take_profit_is_price=False,
        stop_loss=lc,
        stop_loss_is_price=False,
        units=10000,
        name="baseline",
        priority=5,
        order_timeout_min=45,
    )

    plan = OrderPlanner().plan(intent, OrderContext(current_price, "2026/01/02 03:04:05", 0.12))
    legacy_plan = legacy_order.exe_order_plan

    assert plan.target_price == legacy_plan["target_price"]
    assert plan.take_profit_price == legacy_plan["tp_price"]
    assert plan.stop_loss_price == legacy_plan["lc_price"]
    assert order_plan_to_legacy_dict(plan)["for_api_json"] == legacy_plan["for_api_json"]

    wire_order = broker_request_to_oanda(plan.broker_request)["order"]
    legacy_order_payload = legacy_plan["for_api_json"]["order"]
    assert {
        key: wire_order[key]
        for key in (
            "instrument",
            "units",
            "type",
            "positionFill",
            "takeProfitOnFill",
            "stopLossOnFill",
        )
    } == {
        key: legacy_order_payload[key]
        for key in (
            "instrument",
            "units",
            "type",
            "positionFill",
            "takeProfitOnFill",
            "stopLossOnFill",
        )
    }
    if order_type is OrderType.MARKET:
        assert wire_order["timeInForce"] == "FOK"
        assert "price" not in wire_order
    else:
        assert wire_order["timeInForce"] == "GTC"
        assert wire_order["price"] == legacy_order_payload["price"]


@pytest.mark.contract
def test_order_planner_generates_stable_short_submission_fingerprint():
    intent = OrderIntent(
        pair="USD_JPY",
        direction=Direction.BUY,
        order_type=OrderType.LIMIT,
        target=150.1,
        target_is_price=True,
        take_profit=0.2,
        take_profit_is_price=False,
        stop_loss=0.1,
        stop_loss_is_price=False,
        units=100,
        name="M5LineBreakout_upper_0_12:00",
        priority=1,
        order_timeout_min=30,
    )
    context = OrderContext(150.0, "2026/01/02 12:00:00")

    first = OrderPlanner().plan(intent, context)
    second = OrderPlanner().plan(intent, context)
    changed = OrderPlanner().plan(
        OrderIntent(
            **{
                **intent.__dict__,
                "name": "M5LineBreakout_upper_1_12:00",
            }
        ),
        context,
    )

    assert first.broker_request.client_reference == second.broker_request.client_reference
    assert first.broker_request.client_reference != changed.broker_request.client_reference
    assert first.broker_request.client_reference.startswith("ogm-")
    assert first.broker_request.client_reference.isascii()
    assert len(first.broker_request.client_reference) <= 32
