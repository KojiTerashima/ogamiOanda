from dataclasses import dataclass, field

import pytest

from classOrderCreate import Order
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
def test_order_planner_matches_legacy_order_price_and_payload(
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
    assert OrderPlanner.oanda_payload(plan) == legacy_plan["for_api_json"]
