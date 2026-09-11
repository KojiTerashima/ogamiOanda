"""Five-second Bid/Ask execution with a quantity-based authoritative ledger."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, replace
from datetime import datetime
import math
from typing import Callable

from ogami_oanda.application.ports.broker import (
    AccountCapabilities, BrokerTransaction, BrokerTransactionBatch,
    ExecutionResult, InstrumentTradingRules, OrderSubmissionResult,
)
from ogami_oanda.application.ports.clock import Clock
from ogami_oanda.domain.market.currency_pair import currency_pair
from ogami_oanda.domain.market.history import HistoricalCandle, OHLC
from ogami_oanda.domain.orders.models import BrokerOrderRequest, OrderType
from ogami_oanda.domain.positions.models import OrderState, PositionSnapshot, TradeState


@dataclass
class SimulatedTrade:
    request: BrokerOrderRequest
    snapshot: PositionSnapshot
    initial_units: int
    take_profit: float
    stop_loss: float
    closed_units: int = 0
    close_value: float = 0.0
    realized: float = 0.0


class SimulatedBroker:
    def __init__(self, pair: str, clock: Clock, *, initial_balance: float,
                 slippage_pips: float = 0, event_sink: Callable[[dict], None] | None = None) -> None:
        self.pair_info = currency_pair(pair)
        if not math.isfinite(initial_balance) or initial_balance <= 0:
            raise ValueError("initial balance must be finite and positive")
        if not math.isfinite(slippage_pips) or slippage_pips < 0:
            raise ValueError("slippage must be finite and nonnegative")
        self.pair = pair
        self.clock = clock
        self.initial_balance = float(initial_balance)
        self.balance = float(initial_balance)
        self.slippage = slippage_pips * self.pair_info.pip_value
        self.event_sink = event_sink or (lambda event: None)
        self.operation_reason: Callable[[str], str] = lambda reference: ""
        self.orders: dict[str, tuple[BrokerOrderRequest, PositionSnapshot]] = {}
        self.trades: dict[str, SimulatedTrade] = {}
        self._closes: dict[str, int] = {}
        self._order_sequence = 0
        self._trade_sequence = 0
        self._event_sequence = 0
        self._transactions: deque[BrokerTransaction] = deque(maxlen=4096)
        self.last: HistoricalCandle | None = None
        self.finalized = False
        self.completed_trades = 0
        self.winning_trades = 0
        self.gross_profit = 0.0
        self.gross_loss = 0.0
        self.total_pips = 0.0
        self.monthly: dict[str, float] = {}

    def _event(self, kind: str, snapshot: PositionSnapshot | None = None, *,
               time: datetime | None = None, price: float | None = None, units: int = 0,
               realized_pl: float = 0, reason: str = "") -> None:
        self._event_sequence += 1
        at = time or self.clock.now()
        if snapshot is not None and kind in {"CANCEL", "CLOSE_REQUEST", "AMEND"}:
            reason = self.operation_reason(snapshot.trade_id or snapshot.order_id or "") or reason
        event = {"event_id": str(self._event_sequence), "time": at.isoformat(), "event": kind,
                 "pair": self.pair, "order_id": snapshot.order_id if snapshot else "",
                 "trade_id": snapshot.trade_id if snapshot else "",
                 "client_reference": snapshot.client_reference if snapshot else "",
                 "direction": snapshot.direction if snapshot else None,
                 "units": units, "price": price, "realized_pl": realized_pl, "reason": reason}
        self.event_sink(event)
        self._transactions.append(BrokerTransaction(
            str(self._event_sequence), kind, event["order_id"] or None, event["trade_id"] or None,
            event["client_reference"], self.pair, units, price, reason, at,
        ))

    def submit(self, request: BrokerOrderRequest) -> OrderSubmissionResult:
        if self.finalized:
            raise RuntimeError("simulation broker is finalized")
        prices = (request.price, request.take_profit_price, request.stop_loss_price)
        reason = ""
        if request.instrument != self.pair:
            reason = "pair_mismatch"
        elif type(request.units) is not int or not 0 < abs(request.units) <= 1_000_000:
            reason = "invalid_units"
        elif not isinstance(request.order_type, OrderType) or not all(math.isfinite(p) and p > 0 for p in prices):
            reason = "invalid_order"
        elif (request.take_profit_price - request.price) * request.units <= 0 or (request.price - request.stop_loss_price) * request.units <= 0:
            reason = "invalid_protection"
        if reason:
            self._event("REJECT", reason=reason)
            return OrderSubmissionResult.rejected(reason)
        self._order_sequence += 1
        order_id = f"order-{self._order_sequence}"
        snapshot = PositionSnapshot(request.client_reference, self.pair, OrderState.PENDING,
                                    TradeState.NONE, order_id=order_id, life=True,
                                    direction=1 if request.units > 0 else -1,
                                    target_price=request.price, units=abs(request.units),
                                    current_stop_loss=request.stop_loss_price,
                                    client_reference=request.client_reference)
        self.orders[order_id] = (request, snapshot)
        self._event("SUBMIT", snapshot, price=request.price, units=abs(request.units), reason=request.order_type.value)
        return OrderSubmissionResult.pending(order_id)

    def cancel_order(self, order_id: str, *, reason: str = "CANCEL_REQUEST") -> ExecutionResult:
        current = self.orders.get(order_id)
        if current is None or current[1].order_state is not OrderState.PENDING:
            return ExecutionResult(False, order_id, "order_not_pending")
        request, snapshot = current
        snapshot = replace(snapshot, order_state=OrderState.CANCELLED, life=False)
        self.orders[order_id] = (request, snapshot)
        self._event("CANCEL", snapshot, reason=reason)
        return ExecutionResult(True, order_id)

    def close_trade(self, trade_id: str, units: int | None = None) -> ExecutionResult:
        trade = self.trades.get(trade_id)
        if trade is None or trade.snapshot.trade_state is not TradeState.OPEN:
            return ExecutionResult(False, trade_id, "trade_not_open")
        reserved = self._closes.get(trade_id, 0)
        amount = trade.snapshot.units - reserved if units is None else units
        if type(amount) is not int or amount <= 0 or amount + reserved > trade.snapshot.units:
            return ExecutionResult(False, trade_id, "invalid_close_units")
        self._closes[trade_id] = reserved + amount
        self._event("CLOSE_REQUEST", trade.snapshot, units=amount)
        return ExecutionResult(True, trade_id)

    def amend_protection(self, trade_id: str, take_profit_price: float | None,
                         stop_loss_price: float | None) -> ExecutionResult:
        trade = self.trades.get(trade_id)
        if trade is None or trade.snapshot.trade_state is not TradeState.OPEN:
            return ExecutionResult(False, trade_id, "trade_not_open")
        values = [p for p in (take_profit_price, stop_loss_price) if p is not None]
        if not all(math.isfinite(p) and p > 0 for p in values):
            return ExecutionResult(False, trade_id, "invalid_protection")
        if take_profit_price is not None:
            trade.take_profit = take_profit_price
        if stop_loss_price is not None:
            trade.stop_loss = stop_loss_price
            trade.snapshot = replace(trade.snapshot, current_stop_loss=stop_loss_price)
        self._event("AMEND", trade.snapshot, price=stop_loss_price, reason="protection")
        return ExecutionResult(True, trade_id)

    def advance(self, candle: HistoricalCandle) -> None:
        if self.finalized:
            raise RuntimeError("simulation broker is finalized")
        if self.last is not None and candle.time <= self.last.time:
            raise ValueError("broker candles must be in strictly increasing order")
        self.last = candle
        # Previously requested market closes precede this interval's protection.
        for trade_id, units in tuple(self._closes.items()):
            trade = self.trades[trade_id]
            if trade.snapshot.trade_state is TradeState.OPEN:
                price = self._exit_prices(trade, candle).open - trade.snapshot.direction * self.slippage
                self._close(trade, min(units, trade.snapshot.units), price, candle.time, "MARKET_CLOSE")
        self._closes.clear()
        for trade in tuple(self.trades.values()):
            if trade.snapshot.trade_state is TradeState.OPEN:
                self._protect(trade, candle, allow_tp=True)
        for order_id, (request, snapshot) in tuple(self.orders.items()):
            if snapshot.order_state is not OrderState.PENDING:
                continue
            entry = self._entry(request, candle)
            if entry is None:
                continue
            price, at_open = entry
            self._trade_sequence += 1
            trade_id = f"trade-{self._trade_sequence}"
            at = candle.time if at_open else candle.end
            opened = replace(snapshot, order_state=OrderState.FILLED, trade_state=TradeState.OPEN,
                             trade_id=trade_id, target_price=price, current_price=price,
                             open_time=at.isoformat())
            trade = SimulatedTrade(request, opened, abs(request.units), request.take_profit_price, request.stop_loss_price)
            self.trades[trade_id] = trade
            self.orders[order_id] = (request, opened)
            self._event("FILL", opened, time=at, price=price, units=opened.units)
            self._protect(trade, candle, allow_tp=at_open, check_open=at_open)
        for trade in self.trades.values():
            if trade.snapshot.trade_state is TradeState.OPEN:
                price = self._exit_prices(trade, candle).close
                unrealized = (price - trade.snapshot.target_price) * trade.snapshot.direction * trade.snapshot.units
                elapsed = (candle.end - datetime.fromisoformat(trade.snapshot.open_time)).total_seconds()
                trade.snapshot = replace(trade.snapshot, current_price=price, unrealized_pl=unrealized, elapsed_seconds=elapsed)

    def _entry(self, request: BrokerOrderRequest, candle: HistoricalCandle) -> tuple[float, bool] | None:
        direction = 1 if request.units > 0 else -1
        prices = candle.ask if direction > 0 else candle.bid
        target = request.price
        if request.order_type is OrderType.MARKET:
            return prices.open + direction * self.slippage, True
        if request.order_type is OrderType.LIMIT:
            if (prices.open - target) * direction <= 0:
                return prices.open, True
            hit = prices.low <= target if direction > 0 else prices.high >= target
            return (target, False) if hit else None
        if (prices.open - target) * direction >= 0:
            return prices.open + direction * self.slippage, True
        hit = prices.high >= target if direction > 0 else prices.low <= target
        return (target + direction * self.slippage, False) if hit else None

    @staticmethod
    def _exit_prices(trade: SimulatedTrade, candle: HistoricalCandle) -> OHLC:
        return candle.bid if trade.snapshot.direction > 0 else candle.ask

    def _protect(self, trade: SimulatedTrade, candle: HistoricalCandle, *, allow_tp: bool,
                 check_open: bool = True) -> None:
        price = self._exit_prices(trade, candle)
        direction = trade.snapshot.direction
        if check_open and (price.open - trade.stop_loss) * direction <= 0:
            self._close(trade, trade.snapshot.units, price.open - direction * self.slippage, candle.time, "STOP_LOSS")
            return
        sl_hit = price.low <= trade.stop_loss if direction > 0 else price.high >= trade.stop_loss
        tp_hit = price.high >= trade.take_profit if direction > 0 else price.low <= trade.take_profit
        if sl_hit:
            self._close(trade, trade.snapshot.units, trade.stop_loss - direction * self.slippage, candle.end, "STOP_LOSS")
        elif check_open and allow_tp and (price.open - trade.take_profit) * direction >= 0:
            self._close(trade, trade.snapshot.units, price.open, candle.time, "TAKE_PROFIT")
        elif allow_tp and tp_hit:
            self._close(trade, trade.snapshot.units, trade.take_profit, candle.end, "TAKE_PROFIT")

    def _close(self, trade: SimulatedTrade, units: int, price: float, at: datetime, reason: str) -> None:
        pnl = (price - trade.snapshot.target_price) * trade.snapshot.direction * units
        self.balance += pnl
        month = at.isoformat()[:7]
        self.monthly[month] = self.monthly.get(month, 0) + pnl
        trade.realized += pnl
        trade.closed_units += units
        trade.close_value += units * price
        remaining = trade.snapshot.units - units
        closed = remaining == 0
        trade.snapshot = replace(trade.snapshot, units=remaining, realized_pl=trade.realized,
                                 trade_state=TradeState.CLOSED if closed else TradeState.OPEN,
                                 life=not closed, current_price=price,
                                 average_close_price=trade.close_value / trade.closed_units,
                                 close_time=at.isoformat() if closed else None,
                                 close_reason=reason if closed else "", unrealized_pl=0)
        self._event("CLOSE" if closed else "REDUCE", trade.snapshot, time=at, price=price,
                    units=units, realized_pl=pnl, reason=reason)
        if closed:
            self.completed_trades += 1
            self.winning_trades += trade.realized > 0
            self.gross_profit += max(0, trade.realized)
            self.gross_loss += max(0, -trade.realized)
            self.total_pips += trade.realized / trade.initial_units / self.pair_info.pip_value

    def finalize(self) -> None:
        if self.finalized:
            return
        self.finalized = True
        for order_id, (_, snapshot) in tuple(self.orders.items()):
            if snapshot.order_state is OrderState.PENDING:
                self.cancel_order(order_id, reason="END_OF_TEST")
        self._closes.clear()
        if self.last is not None:
            for trade in self.trades.values():
                if trade.snapshot.trade_state is TradeState.OPEN:
                    price = self._exit_prices(trade, self.last).close
                    self._close(trade, trade.snapshot.units, price, self.last.end, "END_OF_TEST")

    @property
    def unrealized_pl(self) -> float:
        return sum(t.snapshot.unrealized_pl for t in self.trades.values() if t.snapshot.trade_state is TradeState.OPEN)

    def order(self, order_id: str) -> PositionSnapshot | None:
        value = self.orders.get(order_id)
        if value is None:
            return None
        snapshot = value[1]
        return self.trade(snapshot.trade_id) if snapshot.trade_id is not None else snapshot

    def trade(self, trade_id: str) -> PositionSnapshot | None:
        trade = self.trades.get(trade_id)
        return None if trade is None else trade.snapshot

    def position(self, reference_id: str) -> PositionSnapshot | None:
        return self.order(reference_id) or self.trade(reference_id)

    def pending_orders(self) -> list[PositionSnapshot]:
        return [s for _, s in self.orders.values() if s.order_state is OrderState.PENDING]

    def open_positions(self) -> list[PositionSnapshot]:
        return [t.snapshot for t in self.trades.values() if t.snapshot.trade_state is TradeState.OPEN]

    def account_capabilities(self) -> AccountCapabilities:
        return AccountCapabilities("simulation", True, str(self._event_sequence))

    def instrument_rules(self, pair: str) -> InstrumentTradingRules:
        if pair != self.pair:
            raise ValueError("unsupported simulation pair")
        return InstrumentTradingRules(pair, 1, 1_000_000, 0)

    def transactions_since(self, transaction_id: str) -> BrokerTransactionBatch:
        cursor = int(transaction_id)
        if self._transactions and cursor < int(self._transactions[0].transaction_id) - 1:
            raise ValueError("simulation transaction cursor expired")
        return BrokerTransactionBatch(tuple(t for t in self._transactions if int(t.transaction_id) > cursor), str(self._event_sequence))

    def release_inactive(self, order_ids: set[str], trade_ids: set[str]) -> None:
        """Keep terminal evidence only while application slots can reference it."""
        for order_id in tuple(self.orders):
            if order_id not in order_ids and self.orders[order_id][1].order_state is not OrderState.PENDING:
                del self.orders[order_id]
        for trade_id in tuple(self.trades):
            if trade_id not in trade_ids and self.trades[trade_id].snapshot.trade_state is TradeState.CLOSED:
                del self.trades[trade_id]
