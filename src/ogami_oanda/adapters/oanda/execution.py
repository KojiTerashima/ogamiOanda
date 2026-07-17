from __future__ import annotations

from oandapyV20.endpoints.orders import OrderCancel, OrderCreate
from oandapyV20.endpoints.trades import TradeClose, TradeCRCDO

from ogami_oanda.adapters.oanda.client import OandaClient
from ogami_oanda.adapters.oanda.mappers import (
    broker_request_to_oanda,
    map_order_create_response,
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
        self.client.request(OrderCancel(accountID=self.client.account_id, orderID=order_id))
        return ExecutionResult(accepted=True, reference_id=order_id)

    def close_trade(self, trade_id: str, units: int | None = None) -> ExecutionResult:
        data = None if units is None else {"units": str(units)}
        self.client.request(TradeClose(accountID=self.client.account_id, tradeID=trade_id, data=data))
        return ExecutionResult(accepted=True, reference_id=trade_id)

    def amend_protection(self, trade_id: str, take_profit_price: float | None, stop_loss_price: float | None) -> ExecutionResult:
        data: dict[str, object] = {}
        if take_profit_price is not None:
            data["takeProfit"] = {"price": str(take_profit_price), "timeInForce": "GTC"}
        if stop_loss_price is not None:
            data["stopLoss"] = {"price": str(stop_loss_price), "timeInForce": "GTC"}
        self.client.request(TradeCRCDO(accountID=self.client.account_id, tradeID=trade_id, data=data))
        return ExecutionResult(accepted=True, reference_id=trade_id)
