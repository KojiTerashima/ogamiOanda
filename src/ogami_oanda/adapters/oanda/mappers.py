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
    """Translate OANDA candle JSON into the canonical market-data contract."""
    rows = []
    for candle in response.get("candles", []):
        if not isinstance(candle, Mapping):
            continue
        price = next(
            (
                candle.get(component)
                for component in ("mid", "ask", "bid")
                if isinstance(candle.get(component), Mapping)
            ),
            None,
        )
        if price is None:
            continue
        timestamp = pd.to_datetime(candle["time"], utc=True).tz_convert("Asia/Tokyo")
        rows.append(
            {
                "time_jp": timestamp.strftime("%Y/%m/%d %H:%M:%S"),
                "time_jp_dt": timestamp.tz_localize(None),
                "open": float(price["o"]),
                "close": float(price["c"]),
                "high": float(price["h"]),
                "low": float(price["l"]),
                "volume": int(candle.get("volume", 0)),
                "time": str(candle["time"]),
            }
        )
    columns = ("time_jp", "time_jp_dt", "open", "close", "high", "low", "volume", "time")
    return pd.DataFrame(rows, columns=columns).sort_values("time_jp_dt", ascending=False).reset_index(drop=True)


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


def map_order_cancel_response(
    response: Mapping[str, object],
    order_id: str,
) -> tuple[bool, str | None, str]:
    transaction = response.get("orderCancelTransaction")
    if isinstance(transaction, Mapping):
        reference_id = transaction.get("orderID", order_id)
        return True, str(reference_id), ""
    return False, None, _execution_rejection_reason(
        response,
        ("orderCancelRejectTransaction",),
        "OANDA did not confirm order cancellation",
    )


def map_trade_close_response(
    response: Mapping[str, object],
    trade_id: str,
) -> tuple[bool, str | None, str]:
    transaction = response.get("orderFillTransaction")
    if isinstance(transaction, Mapping):
        return True, _closed_trade_id(transaction, trade_id), ""
    return False, None, _execution_rejection_reason(
        response,
        ("orderRejectTransaction", "orderCancelTransaction"),
        "OANDA did not confirm trade closure",
    )


def map_trade_protection_response(
    response: Mapping[str, object],
    trade_id: str,
) -> tuple[bool, str | None, str]:
    rejection_keys = (
        "takeProfitOrderRejectTransaction",
        "stopLossOrderRejectTransaction",
        "trailingStopLossOrderRejectTransaction",
        "guaranteedStopLossOrderRejectTransaction",
    )
    if any(isinstance(response.get(key), Mapping) for key in rejection_keys):
        return False, None, _execution_rejection_reason(
            response,
            rejection_keys,
            "OANDA rejected the protection amendment",
        )
    success_keys = (
        "takeProfitOrderTransaction",
        "stopLossOrderTransaction",
        "trailingStopLossOrderTransaction",
        "guaranteedStopLossOrderTransaction",
        "takeProfitOrderCancelTransaction",
        "stopLossOrderCancelTransaction",
        "trailingStopLossOrderCancelTransaction",
        "guaranteedStopLossOrderCancelTransaction",
    )
    if any(isinstance(response.get(key), Mapping) for key in success_keys):
        return True, trade_id, ""
    return False, None, _execution_rejection_reason(
        response,
        rejection_keys,
        "OANDA did not confirm the protection amendment",
    )


def oanda_error_reason(payload: Mapping[str, object], fallback: str) -> str:
    error_code = payload.get("errorCode")
    error_message = payload.get("errorMessage")
    if error_code is not None and error_message is not None:
        return f"{error_code}: {error_message}"
    if error_message is not None:
        return str(error_message)
    if error_code is not None:
        return str(error_code)
    return fallback


def _execution_rejection_reason(
    response: Mapping[str, object],
    transaction_keys: tuple[str, ...],
    fallback: str,
) -> str:
    for key in transaction_keys:
        transaction = response.get(key)
        if not isinstance(transaction, Mapping):
            continue
        for reason_key in ("rejectReason", "reason"):
            if transaction.get(reason_key) is not None:
                return str(transaction[reason_key])
    return oanda_error_reason(response, fallback)


def _closed_trade_id(transaction: Mapping[str, object], fallback: str) -> str:
    reduced = transaction.get("tradeReduced")
    if isinstance(reduced, Mapping) and reduced.get("tradeID") is not None:
        return str(reduced["tradeID"])
    closed = transaction.get("tradesClosed")
    if isinstance(closed, list) and closed and isinstance(closed[0], Mapping):
        trade_id = closed[0].get("tradeID")
        if trade_id is not None:
            return str(trade_id)
    return fallback


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
    units = int(float(order.get("units", 0)))
    return PositionSnapshot(
        name=str(order.get("clientExtensions", {}).get("tag", order.get("id", ""))),
        pair=str(order.get("instrument", "USD_JPY")),
        order_state=order_state,
        trade_state=TradeState.OPEN if trade_id else TradeState.NONE,
        order_id=str(order.get("id", "")) or None,
        trade_id=trade_id,
        life=order_state in {OrderState.PENDING, OrderState.FILLED},
        direction=1 if units > 0 else -1 if units < 0 else None,
        target_price=float(order["price"]) if order.get("price") is not None else None,
        units=abs(units),
        current_price=float(order["price"]) if order.get("price") is not None else None,
    )


def map_trade_snapshot(response: Mapping[str, object]) -> PositionSnapshot | None:
    trade = response.get("trade")
    if not isinstance(trade, Mapping):
        return None
    state = str(trade.get("state", "")).upper()
    trade_state = TradeState.OPEN if state == "OPEN" else TradeState.CLOSED if state == "CLOSED" else TradeState.ERROR
    units = int(float(trade.get("currentUnits", trade.get("initialUnits", 0))))
    return PositionSnapshot(
        name=str(trade.get("clientExtensions", {}).get("tag", trade.get("id", ""))),
        pair=str(trade.get("instrument", "USD_JPY")),
        order_state=OrderState.FILLED,
        trade_state=trade_state,
        trade_id=str(trade.get("id", "")) or None,
        life=trade_state is TradeState.OPEN,
        direction=1 if units > 0 else -1 if units < 0 else None,
        target_price=float(trade["price"]) if trade.get("price") is not None else None,
        units=abs(units),
        current_stop_loss=float(trade["stopLossOrder"]["price"])
        if isinstance(trade.get("stopLossOrder"), Mapping) and trade["stopLossOrder"].get("price") is not None
        else None,
        current_price=float(trade["currentPrice"]) if trade.get("currentPrice") is not None else None,
        unrealized_pl=float(trade.get("unrealizedPL", 0)),
        realized_pl=float(trade.get("realizedPL", 0)),
        open_time=str(trade.get("openTime")) if trade.get("openTime") is not None else None,
        close_time=str(trade.get("closeTime")) if trade.get("closeTime") is not None else None,
        elapsed_seconds=float(trade.get("time_past", 0)),
        average_close_price=float(trade["averageClosePrice"])
        if trade.get("averageClosePrice") is not None
        else None,
    )
