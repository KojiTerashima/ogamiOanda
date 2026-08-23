from __future__ import annotations

from oandapyV20.endpoints.accounts import AccountSummary
from oandapyV20.endpoints.orders import OrderDetails, OrdersPending
from oandapyV20.endpoints.trades import OpenTrades, TradeDetails

from ogami_oanda.adapters.oanda.client import OandaClient
from ogami_oanda.adapters.oanda.mappers import map_order_snapshot, map_trade_snapshot
from ogami_oanda.application.ports.broker import AccountCapabilities
from ogami_oanda.domain.positions.models import PositionSnapshot


class OandaQueryAdapter:
    def __init__(self, client: OandaClient) -> None:
        self.client = client

    def account_capabilities(self) -> AccountCapabilities:
        response = self.client.request(
            AccountSummary(accountID=self.client.account_id)
        )
        account = response.get("account", {})
        return AccountCapabilities(
            account_id=str(account.get("id", self.client.account_id)),
            hedging_enabled=bool(account.get("hedgingEnabled", False)),
        )

    def position(self, reference_id: str) -> PositionSnapshot | None:
        order = self.order(reference_id)
        if order is not None:
            return order
        return self.trade(reference_id)

    def order(self, order_id: str) -> PositionSnapshot | None:
        response = self.client.request(OrderDetails(accountID=self.client.account_id, orderID=order_id))
        return map_order_snapshot(response)

    def trade(self, trade_id: str) -> PositionSnapshot | None:
        response = self.client.request(TradeDetails(accountID=self.client.account_id, tradeID=trade_id))
        return map_trade_snapshot(response)

    def pending_orders(self) -> list[PositionSnapshot]:
        response = self.client.request(OrdersPending(accountID=self.client.account_id))
        return [snapshot for order in response.get("orders", []) if (snapshot := map_order_snapshot({"order": order})) is not None]

    def open_positions(self) -> list[PositionSnapshot]:
        response = self.client.request(OpenTrades(accountID=self.client.account_id))
        return [
            snapshot
            for trade in response.get("trades", [])
            if (snapshot := map_trade_snapshot({"trade": trade})) is not None
        ]

    def legacy_open_position(self, reference_id: str) -> PositionSnapshot | None:
        for position in self.open_positions():
            if position.trade_id == reference_id or position.order_id == reference_id:
                return position
        return None
