from __future__ import annotations

from datetime import datetime
from typing import Mapping

import pandas as pd

from ogami_oanda.domain.market.currency_pair import currency_pair
from ogami_oanda.domain.orders.models import BrokerOrderRequest, OrderType
from ogami_oanda.domain.positions.models import OrderState, PositionSnapshot, TradeState
from ogami_oanda.application.ports.broker import OrderSubmissionResult


def map_price_response(pair_name: str, response: Mapping[str, object]) -> dict[str, object]:
    price = response["prices"][0]
    pair = currency_pair(pair_name)
    bid = pair.round_price(float(price["bids"][0]["price"]))
    ask = pair.round_price(float(price["asks"][0]["price"]))
    mapped = {
        "bid": bid,
        "ask": ask,
        "mid": pair.round_price((bid + ask) / 2),
        "spread": pair.round_price(ask - bid),
        "tradeable": str(price.get("status", "tradeable")).lower()
        == "tradeable",
    }
    source_time = _parse_source_time(price.get("time"))
    if source_time is not None:
        mapped["source_time"] = source_time
    return mapped


def _parse_source_time(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"OANDA price time is invalid: {value!r}") from exc
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ValueError(f"OANDA price time must be timezone-aware: {value!r}")
    return timestamp


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
                "complete": candle.get("complete") is True,
            }
        )
    columns = ("time_jp", "time_jp_dt", "open", "close", "high", "low", "volume", "time", "complete")
    return pd.DataFrame(rows, columns=columns).sort_values("time_jp_dt", ascending=False).reset_index(drop=True)


def broker_request_to_oanda(
    request: BrokerOrderRequest,
    *,
    include_client_extensions: bool = False,
) -> dict[str, object]:
    pair = currency_pair(request.instrument)
    order = {
        "instrument": request.instrument,
        "units": str(request.units),
        "type": request.order_type.value,
        "timeInForce": "FOK" if request.order_type is OrderType.MARKET else "GTC",
        "positionFill": "DEFAULT",
        "takeProfitOnFill": {"timeInForce": "GTC", "price": pair.price_to_str(request.take_profit_price)},
        "stopLossOnFill": {"timeInForce": "GTC", "price": pair.price_to_str(request.stop_loss_price)},
    }
    if request.order_type is not OrderType.MARKET:
        order["price"] = pair.price_to_str(request.price)
    if include_client_extensions and request.client_reference:
        extensions = {
            "id": request.client_reference,
            "tag": "ogami-oanda",
        }
        order["clientExtensions"] = extensions
        order["tradeClientExtensions"] = dict(extensions)
    return {"order": order}


def map_order_create_response(response: Mapping[str, object]) -> OrderSubmissionResult:
    rejected = response.get("orderRejectTransaction")
    if isinstance(rejected, Mapping):
        return OrderSubmissionResult.rejected(
            _transaction_reason(rejected, response, "OANDA rejected order creation")
        )

    created = response.get("orderCreateTransaction")
    order_id = (
        str(created["id"])
        if isinstance(created, Mapping) and created.get("id") is not None
        else None
    )
    cancelled = response.get("orderCancelTransaction")
    if isinstance(cancelled, Mapping):
        cancelled_order_id = cancelled.get("orderID", order_id)
        return OrderSubmissionResult.cancelled(
            _transaction_reason(cancelled, response, "OANDA cancelled order on creation"),
            order_id=str(cancelled_order_id) if cancelled_order_id is not None else None,
        )

    filled = response.get("orderFillTransaction")
    if isinstance(filled, Mapping):
        fill_order_id = filled.get("orderID", order_id)
        opened = filled.get("tradeOpened")
        if isinstance(opened, Mapping) and opened.get("tradeID") is not None:
            raw_price = opened.get("price", filled.get("price"))
            return OrderSubmissionResult.filled(
                order_id=str(fill_order_id) if fill_order_id is not None else None,
                trade_id=str(opened["tradeID"]),
                fill_price=float(raw_price) if raw_price is not None else None,
            )
        affected_trade_ids = _affected_trade_ids(filled)
        if affected_trade_ids:
            return OrderSubmissionResult.terminal(
                "entry order reduced or closed an existing trade",
                order_id=str(fill_order_id) if fill_order_id is not None else None,
                affected_trade_ids=affected_trade_ids,
            )
        return OrderSubmissionResult.terminal(
            "order fill did not open a managed trade",
            order_id=str(fill_order_id) if fill_order_id is not None else None,
        )

    if order_id is not None:
        return OrderSubmissionResult.pending(order_id)
    return OrderSubmissionResult.unknown("OANDA order response had no recognized transaction")


def _transaction_reason(
    transaction: Mapping[str, object],
    response: Mapping[str, object],
    fallback: str,
) -> str:
    for key in ("rejectReason", "reason"):
        if transaction.get(key) is not None:
            return str(transaction[key])
    return oanda_error_reason(response, fallback)


def _affected_trade_ids(transaction: Mapping[str, object]) -> tuple[str, ...]:
    ids: list[str] = []
    reduced = transaction.get("tradeReduced")
    if isinstance(reduced, Mapping) and reduced.get("tradeID") is not None:
        ids.append(str(reduced["tradeID"]))
    closed = transaction.get("tradesClosed")
    if isinstance(closed, list):
        ids.extend(
            str(item["tradeID"])
            for item in closed
            if isinstance(item, Mapping) and item.get("tradeID") is not None
        )
    return tuple(ids)


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
    client_extensions = order.get("clientExtensions")
    if not isinstance(client_extensions, Mapping):
        client_extensions = {}
    return PositionSnapshot(
        name=str(client_extensions.get("tag", order.get("id", ""))),
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
        client_reference=str(client_extensions.get("id", "")),
    )


def map_trade_snapshot(response: Mapping[str, object]) -> PositionSnapshot | None:
    trade = response.get("trade")
    if not isinstance(trade, Mapping):
        return None
    state = str(trade.get("state", "")).upper()
    trade_state = TradeState.OPEN if state == "OPEN" else TradeState.CLOSED if state == "CLOSED" else TradeState.ERROR
    units = int(float(trade.get("currentUnits", trade.get("initialUnits", 0))))
    client_extensions = trade.get("clientExtensions")
    if not isinstance(client_extensions, Mapping):
        client_extensions = {}
    return PositionSnapshot(
        name=str(client_extensions.get("tag", trade.get("id", ""))),
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
        client_reference=str(client_extensions.get("id", "")),
    )
