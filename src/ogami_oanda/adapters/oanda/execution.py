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
from ogami_oanda.application.ports.broker import (
    ExecutionResult,
    MutationState,
    OrderSubmissionResult,
)
from ogami_oanda.application.errors import TransientExternalServiceError
from ogami_oanda.domain.orders.models import BrokerOrderRequest


class OandaExecutionAdapter:
    def __init__(
        self,
        client: OandaClient,
        *,
        include_client_extensions: bool | None = None,
    ) -> None:
        self.client = client
        self.include_client_extensions = include_client_extensions

    def submit(self, request: BrokerOrderRequest) -> OrderSubmissionResult:
        include_client_extensions = self.include_client_extensions
        if include_client_extensions is None:
            include_client_extensions = bool(
                getattr(
                    getattr(self.client, "account", None),
                    "client_extensions_enabled",
                    False,
                )
            )
        try:
            response = self.client.request(
                OrderCreate(
                    accountID=self.client.account_id,
                    data=broker_request_to_oanda(
                        request,
                        include_client_extensions=include_client_extensions,
                    ),
                )
            )
        except Exception as error:
            return _submission_exception_result(error)
        return map_order_create_response(response)

    def cancel_order(self, order_id: str) -> ExecutionResult:
        try:
            response = self.client.request(OrderCancel(accountID=self.client.account_id, orderID=order_id))
        except Exception as error:
            return _mutation_exception_result(error)
        accepted, reference_id, reason = map_order_cancel_response(response, order_id)
        return ExecutionResult(accepted=accepted, reference_id=reference_id, message=reason)

    def close_trade(self, trade_id: str, units: int | None = None) -> ExecutionResult:
        data = None if units is None else {"units": str(units)}
        try:
            response = self.client.request(TradeClose(accountID=self.client.account_id, tradeID=trade_id, data=data))
        except Exception as error:
            return _mutation_exception_result(error)
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
            return _mutation_exception_result(error)
        accepted, reference_id, reason = map_trade_protection_response(response, trade_id)
        return ExecutionResult(accepted=accepted, reference_id=reference_id, message=reason)


def _submission_exception_result(error: Exception) -> OrderSubmissionResult:
    reason = _exception_reason(error)
    if _is_transient(error):
        return OrderSubmissionResult.unknown(reason)
    if _is_broker_rejection(error):
        return OrderSubmissionResult.rejected(reason)
    raise error


def _mutation_exception_result(error: Exception) -> ExecutionResult:
    reason = _exception_reason(error)
    if _is_transient(error):
        return ExecutionResult(False, message=reason, state=MutationState.UNKNOWN)
    if not _is_broker_rejection(error):
        raise error
    return ExecutionResult(False, message=reason, state=MutationState.REJECTED)


def _exception_reason(error: Exception) -> str:
    raw_message = getattr(error, "msg", None)
    if isinstance(raw_message, Mapping):
        return oanda_error_reason(raw_message, str(error) or error.__class__.__name__)
    return _exception_text(raw_message, error)


def _status_code(error: Exception) -> int | None:
    raw_code = getattr(error, "code", None)
    try:
        return int(raw_code) if raw_code is not None else None
    except (TypeError, ValueError):
        return None


def _is_transient(error: Exception) -> bool:
    if isinstance(error, TransientExternalServiceError):
        return True
    code = _status_code(error)
    if code in {408, 425, 429} or (code is not None and code >= 500):
        return True
    if isinstance(error, (TimeoutError, ConnectionError)):
        return True
    error_name = error.__class__.__name__.lower()
    return "timeout" in error_name or "connection" in error_name or "proxy" in error_name


def _is_broker_rejection(error: Exception) -> bool:
    code = _status_code(error)
    return code is not None and 400 <= code < 500


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
