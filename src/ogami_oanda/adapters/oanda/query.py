from __future__ import annotations

from datetime import datetime

from oandapyV20.endpoints.accounts import AccountInstruments, AccountSummary
from oandapyV20.endpoints.orders import OrderDetails, OrdersPending
from oandapyV20.endpoints.trades import OpenTrades, TradeDetails
from oandapyV20.endpoints.transactions import TransactionsSinceID

from ogami_oanda.adapters.oanda.client import OandaClient
from ogami_oanda.adapters.oanda.mappers import map_order_snapshot, map_trade_snapshot
from ogami_oanda.application.ports.broker import (
    AccountCapabilities,
    BrokerTransaction,
    BrokerTransactionBatch,
    InstrumentTradingRules,
)
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
            last_transaction_id=(
                str(response["lastTransactionID"])
                if response.get("lastTransactionID") is not None
                else None
            ),
        )

    def transactions_since(self, transaction_id: str) -> BrokerTransactionBatch:
        response = self.client.request(
            TransactionsSinceID(
                accountID=self.client.account_id,
                params={"id": transaction_id},
            )
        )
        transactions = tuple(
            _map_transaction(item)
            for item in response.get("transactions", [])
            if isinstance(item, dict)
        )
        return BrokerTransactionBatch(
            transactions,
            str(response["lastTransactionID"])
            if response.get("lastTransactionID") is not None
            else None,
        )

    def instrument_rules(self, pair: str) -> InstrumentTradingRules:
        response = self.client.request(
            AccountInstruments(
                accountID=self.client.account_id,
                params={"instruments": pair},
            )
        )
        matches = [
            item
            for item in response.get("instruments", [])
            if isinstance(item, dict) and item.get("name") == pair
        ]
        if len(matches) != 1:
            raise ValueError(f"Broker did not return unique instrument rules for {pair}")
        instrument = matches[0]
        return InstrumentTradingRules(
            pair=pair,
            minimum_trade_size=int(float(instrument["minimumTradeSize"])),
            maximum_order_units=int(float(instrument["maximumOrderUnits"])),
            trade_units_precision=int(instrument["tradeUnitsPrecision"]),
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


def _map_transaction(transaction: dict[str, object]) -> BrokerTransaction:
    kind = str(transaction.get("type", "UNKNOWN"))
    transaction_id = str(transaction.get("id", ""))
    order_id_value = transaction.get("orderID")
    if order_id_value is None and kind.endswith("_ORDER"):
        order_id_value = transaction.get("id")
    opened = transaction.get("tradeOpened")
    trade_id = None
    price_value = transaction.get("price")
    if isinstance(opened, dict):
        if opened.get("tradeID") is not None:
            trade_id = str(opened["tradeID"])
        if opened.get("price") is not None:
            price_value = opened["price"]
    client_extensions = transaction.get("clientExtensions")
    client_reference = ""
    if isinstance(client_extensions, dict):
        client_reference = str(client_extensions.get("id", ""))
    if not client_reference and transaction.get("clientOrderID") is not None:
        client_reference = str(transaction["clientOrderID"])
    units_value = transaction.get("units", 0)
    occurred_at = (
        datetime.fromisoformat(str(transaction["time"]).replace("Z", "+00:00"))
        if transaction.get("time") is not None
        else None
    )
    return BrokerTransaction(
        transaction_id=transaction_id,
        kind=kind,
        order_id=str(order_id_value) if order_id_value is not None else None,
        trade_id=trade_id,
        client_reference=client_reference,
        pair=str(transaction["instrument"])
        if transaction.get("instrument") is not None
        else None,
        units=int(float(units_value or 0)),
        price=float(price_value) if price_value is not None else None,
        reason=str(transaction.get("rejectReason", transaction.get("reason", ""))),
        occurred_at=occurred_at,
    )
