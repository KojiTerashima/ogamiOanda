from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from ogami_oanda.domain.orders.models import BrokerOrderRequest
from ogami_oanda.domain.positions.models import PositionSnapshot


@dataclass(frozen=True)
class ExecutionResult:
    accepted: bool
    reference_id: str | None = None
    message: str = ""


@runtime_checkable
class BrokerExecutionPort(Protocol):
    def submit(self, request: BrokerOrderRequest) -> ExecutionResult: ...

    def cancel_order(self, order_id: str) -> ExecutionResult: ...

    def close_trade(self, trade_id: str, units: int | None = None) -> ExecutionResult: ...

    def amend_protection(self, trade_id: str, take_profit_price: float | None, stop_loss_price: float | None) -> ExecutionResult: ...


@runtime_checkable
class BrokerQueryPort(Protocol):
    def position(self, reference_id: str) -> PositionSnapshot | None: ...

    def order(self, order_id: str) -> PositionSnapshot | None: ...

    def trade(self, trade_id: str) -> PositionSnapshot | None: ...

    def pending_orders(self) -> list[PositionSnapshot]: ...

    def open_positions(self) -> list[PositionSnapshot]: ...
