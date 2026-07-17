from __future__ import annotations

from typing import Mapping

import pandas as pd

from ogami_oanda.domain.market.currency_pair import currency_pair
from ogami_oanda.domain.orders.models import BrokerOrderRequest
from ogami_oanda.domain.positions.models import OrderState, PositionSnapshot, TradeState


def map_price_response(pair_name: str, response: Mapping[str, object]) -> dict[str, float]:
    price = response["prices"][0]
    pair = currency_pair(pair_name)
    bid = pair.round_price(float(price["bids"][0]["price"]))
    ask = pair.round_price(float(price["asks"][0]["price"]))
    return {"bid": bid, "ask": ask, "mid": pair.round_price((bid + ask) / 2), "spread": pair.round_price(ask - bid)}


def map_candle_response(response: Mapping[str, object]) -> pd.DataFrame:
    return pd.DataFrame(response.get("candles", []))


def broker_request_to_oanda(request: BrokerOrderRequest) -> dict[str, object]:
    pair = currency_pair(request.instrument)
    return {
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


def map_order_create_response(response: Mapping[str, object]) -> tuple[bool, str | None]:
    if "orderCancelTransaction" in response:
        return False, None
    transaction = response.get("orderCreateTransaction", {})
    return True, str(transaction.get("id")) if transaction.get("id") is not None else None


def map_order_snapshot(response: Mapping[str, object]) -> PositionSnapshot | None:
    order = response.get("order")
    if not isinstance(order, Mapping):
        return None
    state = str(order.get("state", "")).upper()
    order_state = {
        "PENDING": OrderState.PENDING,
        "FILLED": OrderState.FILLED,
        "CANCELLED": OrderState.CANCELLED,
        "REJECTED": OrderState.REJECTED,
    }.get(state, OrderState.ERROR)
    trade_id = str(order.get("tradeOpenedID", "")) or None
    return PositionSnapshot(
        name=str(order.get("clientExtensions", {}).get("tag", order.get("id", ""))),
        pair=str(order.get("instrument", "USD_JPY")),
        order_state=order_state,
        trade_state=TradeState.OPEN if trade_id else TradeState.NONE,
        order_id=str(order.get("id", "")) or None,
        trade_id=trade_id,
        life=order_state in {OrderState.PENDING, OrderState.FILLED},
    )


def map_trade_snapshot(response: Mapping[str, object]) -> PositionSnapshot | None:
    trade = response.get("trade")
    if not isinstance(trade, Mapping):
        return None
    state = str(trade.get("state", "")).upper()
    trade_state = TradeState.OPEN if state == "OPEN" else TradeState.CLOSED if state == "CLOSED" else TradeState.ERROR
    return PositionSnapshot(
        name=str(trade.get("clientExtensions", {}).get("tag", trade.get("id", ""))),
        pair=str(trade.get("instrument", "USD_JPY")),
        order_state=OrderState.FILLED,
        trade_state=trade_state,
        trade_id=str(trade.get("id", "")) or None,
        life=trade_state is TradeState.OPEN,
    )
