from __future__ import annotations

from ogami_oanda.application.ports.broker import ExecutionResult
from ogami_oanda.domain.orders.models import BrokerOrderRequest
from ogami_oanda.domain.positions.models import PositionSnapshot


class FakeBroker:
    def __init__(self) -> None:
        self.requests: list[BrokerOrderRequest] = []
        self.commands: list[tuple[str, tuple[object, ...]]] = []
        self.positions: dict[str, PositionSnapshot] = {}
        self.orders: dict[str, PositionSnapshot] = {}
        self.trades: dict[str, PositionSnapshot] = {}

    def submit(self, request: BrokerOrderRequest) -> ExecutionResult:
        self.requests.append(request)
        reference_id = f"order-{len(self.requests)}"
        return ExecutionResult(accepted=True, reference_id=reference_id)

    def cancel_order(self, order_id: str) -> ExecutionResult:
        self.commands.append(("cancel_order", (order_id,)))
        return ExecutionResult(accepted=True, reference_id=order_id)

    def close_trade(self, trade_id: str, units: int | None = None) -> ExecutionResult:
        self.commands.append(("close_trade", (trade_id, units)))
        return ExecutionResult(accepted=True, reference_id=trade_id)

    def amend_protection(self, trade_id: str, take_profit_price: float | None, stop_loss_price: float | None) -> ExecutionResult:
        self.commands.append(("amend_protection", (trade_id, take_profit_price, stop_loss_price)))
        return ExecutionResult(accepted=True, reference_id=trade_id)

    def position(self, reference_id: str) -> PositionSnapshot | None:
        return self.order(reference_id) or self.trade(reference_id) or self.positions.get(reference_id)

    def order(self, order_id: str) -> PositionSnapshot | None:
        return self.orders.get(order_id) or self.positions.get(order_id)

    def trade(self, trade_id: str) -> PositionSnapshot | None:
        return self.trades.get(trade_id) or self.positions.get(trade_id)

    def pending_orders(self) -> list[PositionSnapshot]:
        return [position for position in self.orders.values() if position.order_state.value == "PENDING"]

    def open_positions(self) -> list[PositionSnapshot]:
        return list(self.positions.values())
