from __future__ import annotations

import json
from typing import Mapping

from oandapyV20.endpoints.orders import OrderCancel, OrderCreate
from oandapyV20.endpoints.trades import TradeClose, TradeCRCDO

from ogami_oanda.adapters.oanda.client import OandaClient
from ogami_oanda.adapters.oanda.mappers import (
    broker_request_to_oanda,
    map_order_cancel_response,
    map_order_create_response,
    map_trade_close_response,
    map_trade_protection_response,
    oanda_error_reason,
)
from ogami_oanda.application.ports.broker import ExecutionResult
from ogami_oanda.domain.orders.models import BrokerOrderRequest


class OandaExecutionAdapter:
    def __init__(self, client: OandaClient) -> None:
        self.client = client

    def submit(self, request: BrokerOrderRequest) -> ExecutionResult:
        response = self.client.request(OrderCreate(accountID=self.client.account_id, data=broker_request_to_oanda(request)))
        accepted, reference_id = map_order_create_response(response)
        return ExecutionResult(accepted=accepted, reference_id=reference_id)

    def cancel_order(self, order_id: str) -> ExecutionResult:
        try:
            response = self.client.request(OrderCancel(accountID=self.client.account_id, orderID=order_id))
        except Exception as error:
            return _rejected_exception(error)
        accepted, reference_id, reason = map_order_cancel_response(response, order_id)
        return ExecutionResult(accepted=accepted, reference_id=reference_id, message=reason)

    def close_trade(self, trade_id: str, units: int | None = None) -> ExecutionResult:
        data = None if units is None else {"units": str(units)}
        try:
            response = self.client.request(TradeClose(accountID=self.client.account_id, tradeID=trade_id, data=data))
        except Exception as error:
            return _rejected_exception(error)
        accepted, reference_id, reason = map_trade_close_response(response, trade_id)
        return ExecutionResult(accepted=accepted, reference_id=reference_id, message=reason)

    def amend_protection(self, trade_id: str, take_profit_price: float | None, stop_loss_price: float | None) -> ExecutionResult:
        data: dict[str, object] = {}
        if take_profit_price is not None:
            data["takeProfit"] = {"price": str(take_profit_price), "timeInForce": "GTC"}
        if stop_loss_price is not None:
            data["stopLoss"] = {"price": str(stop_loss_price), "timeInForce": "GTC"}
        try:
            response = self.client.request(TradeCRCDO(accountID=self.client.account_id, tradeID=trade_id, data=data))
        except Exception as error:
            return _rejected_exception(error)
        accepted, reference_id, reason = map_trade_protection_response(response, trade_id)
        return ExecutionResult(accepted=accepted, reference_id=reference_id, message=reason)


def _rejected_exception(error: Exception) -> ExecutionResult:
    raw_message = getattr(error, "msg", None)
    if isinstance(raw_message, Mapping):
        reason = oanda_error_reason(raw_message, str(error) or error.__class__.__name__)
    else:
        reason = _exception_text(raw_message, error)
    return ExecutionResult(accepted=False, message=reason)


def _exception_text(raw_message: object, error: Exception) -> str:
    text = str(raw_message) if raw_message is not None else str(error)
    try:
        payload = json.loads(text)
    except (TypeError, json.JSONDecodeError):
        code = getattr(error, "code", None)
        return f"{code}: {text}" if code is not None and text else text or error.__class__.__name__
    if isinstance(payload, Mapping):
        return oanda_error_reason(payload, text)
    return text or error.__class__.__name__
