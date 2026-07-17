from __future__ import annotations

from ogami_oanda.domain.market.currency_pair import currency_pair
from ogami_oanda.domain.orders.models import (
    BrokerOrderRequest,
    Direction,
    OrderContext,
    OrderIntent,
    OrderPlan,
    OrderType,
)


def legacy_dict_to_order_plan(plan: dict[str, object]) -> OrderPlan:
    pair_name = str(plan["pair"])
    pair = currency_pair(pair_name)
    direction = Direction(int(plan["direction"]))
    order_type = OrderType(str(plan["type"]))
    target_price = float(plan["target_price"])
    take_profit_price = float(plan["tp_price"])
    stop_loss_price = float(plan["lc_price"])
    intent = OrderIntent(
        pair=pair_name,
        direction=direction,
        order_type=order_type,
        target=target_price,
        target_is_price=True,
        take_profit=take_profit_price,
        take_profit_is_price=True,
        stop_loss=stop_loss_price,
        stop_loss_is_price=True,
        units=int(plan["units"]),
        name=str(plan["name"]),
        priority=int(plan["priority"]),
        order_timeout_min=int(plan["order_timeout_min"]),
        trade_timeout_min=int(plan["trade_timeout_min"]),
        lc_change=tuple(plan.get("lc_change", ())),
        metadata={
            key: value
            for key, value in plan.items()
            if key not in {"for_api_json", "candle_analysis_class"}
        },
    )
    context = OrderContext(
        current_price=target_price,
        decision_time=str(plan["decision_time"]),
        move_average=float(plan.get("move_ave", 0)),
        account_mode=int(plan.get("oa_mode", 2)),
    )
    broker_request = BrokerOrderRequest(
        instrument=pair_name,
        units=int(plan["units"]) * direction.value,
        order_type=order_type,
        price=target_price,
        take_profit_price=take_profit_price,
        stop_loss_price=stop_loss_price,
    )
    return OrderPlan(
        intent=intent,
        context=context,
        target_price=pair.round_price(target_price),
        take_profit_price=pair.round_price(take_profit_price),
        stop_loss_price=pair.round_price(stop_loss_price),
        take_profit_range=float(plan["tp_range"]),
        stop_loss_range=float(plan["lc_range"]),
        broker_request=broker_request,
    )


def order_plan_to_legacy_dict(order_plan: OrderPlan) -> dict[str, object]:
    intent = order_plan.intent
    context = order_plan.context
    request = order_plan.broker_request
    pair = currency_pair(intent.pair)
    payload = {
        "order": {
            "instrument": request.instrument,
            "units": str(request.units),
            "type": request.order_type.value,
            "positionFill": "DEFAULT",
            "price": pair.price_to_str(request.price),
            "takeProfitOnFill": {"timeInForce": "GTC", "price": pair.price_to_str(request.take_profit_price)},
            "stopLossOnFill": {"timeInForce": "GTC", "price": pair.price_to_str(request.stop_loss_price)},
        }
    }
    return {
        "decision_time": context.decision_time,
        "units": intent.units,
        "pair": intent.pair,
        "direction": intent.direction.value,
        "target_price": order_plan.target_price,
        "lc_price": order_plan.stop_loss_price,
        "lc_range": order_plan.stop_loss_range,
        "tp_price": order_plan.take_profit_price,
        "tp_range": order_plan.take_profit_range,
        "type": intent.order_type.value,
        "name": intent.name,
        "name_ymdhms": str(intent.metadata.get("name_ymdhms", intent.name)),
        "oa_mode": context.account_mode,
        "order_timeout_min": intent.order_timeout_min,
        "trade_timeout_min": intent.trade_timeout_min,
        "order_permission": bool(intent.metadata.get("order_permission", True)),
        "priority": intent.priority,
        "watching_price": intent.metadata.get("watching_price", 0),
        "lc_price_original": order_plan.stop_loss_price,
        "tp_price_original": order_plan.take_profit_price,
        "for_api_json": payload,
        "lc_change": list(intent.lc_change),
        "move_ave": context.move_average,
        "candle_lc_change_type": intent.metadata.get("candle_lc_change_type", "5M"),
        "memo": intent.metadata.get("memo", ""),
    }