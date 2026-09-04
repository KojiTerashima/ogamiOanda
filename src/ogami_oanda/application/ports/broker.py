from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Protocol, runtime_checkable

from ogami_oanda.domain.orders.models import BrokerOrderRequest
from ogami_oanda.domain.positions.models import PositionSnapshot


class MutationState(str, Enum):
    CONFIRMED = "CONFIRMED"
    REJECTED = "REJECTED"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class ExecutionResult:
    accepted: bool
    reference_id: str | None = None
    message: str = ""
    state: MutationState | None = None

    def __post_init__(self) -> None:
        if self.state is None:
            state = MutationState.CONFIRMED if self.accepted else MutationState.REJECTED
            object.__setattr__(self, "state", state)


class OrderSubmissionState(str, Enum):
    PENDING = "PENDING"
    FILLED = "FILLED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"
    UNKNOWN = "UNKNOWN"
    TERMINAL = "TERMINAL"


@dataclass(frozen=True)
class OrderSubmissionResult:
    state: OrderSubmissionState
    order_id: str | None = None
    trade_id: str | None = None
    fill_price: float | None = None
    reason: str = ""
    affected_trade_ids: tuple[str, ...] = ()
    retry_after_seconds: float | None = None

    @property
    def accepted(self) -> bool:
        return self.state in {OrderSubmissionState.PENDING, OrderSubmissionState.FILLED}

    @property
    def reference_id(self) -> str | None:
        return self.trade_id or self.order_id

    @property
    def message(self) -> str:
        return self.reason

    @classmethod
    def pending(cls, order_id: str) -> "OrderSubmissionResult":
        return cls(OrderSubmissionState.PENDING, order_id=order_id)

    @classmethod
    def filled(
        cls,
        *,
        order_id: str | None,
        trade_id: str,
        fill_price: float | None = None,
    ) -> "OrderSubmissionResult":
        return cls(
            OrderSubmissionState.FILLED,
            order_id=order_id,
            trade_id=trade_id,
            fill_price=fill_price,
        )

    @classmethod
    def rejected(cls, reason: str) -> "OrderSubmissionResult":
        return cls(OrderSubmissionState.REJECTED, reason=reason)

    @classmethod
    def cancelled(
        cls,
        reason: str,
        *,
        order_id: str | None = None,
    ) -> "OrderSubmissionResult":
        return cls(OrderSubmissionState.CANCELLED, order_id=order_id, reason=reason)

    @classmethod
    def unknown(
        cls,
        reason: str,
        *,
        retry_after_seconds: float | None = None,
    ) -> "OrderSubmissionResult":
        return cls(
            OrderSubmissionState.UNKNOWN,
            reason=reason,
            retry_after_seconds=retry_after_seconds,
        )

    @classmethod
    def terminal(
        cls,
        reason: str,
        *,
        order_id: str | None = None,
        affected_trade_ids: tuple[str, ...] = (),
    ) -> "OrderSubmissionResult":
        return cls(
            OrderSubmissionState.TERMINAL,
            order_id=order_id,
            reason=reason,
            affected_trade_ids=affected_trade_ids,
        )


@runtime_checkable
class BrokerExecutionPort(Protocol):
    def submit(self, request: BrokerOrderRequest) -> OrderSubmissionResult: ...

    def cancel_order(self, order_id: str) -> ExecutionResult: ...

    def close_trade(self, trade_id: str, units: int | None = None) -> ExecutionResult: ...

    def amend_protection(self, trade_id: str, take_profit_price: float | None, stop_loss_price: float | None) -> ExecutionResult: ...


@dataclass(frozen=True)
class AccountCapabilities:
    account_id: str
    hedging_enabled: bool
    last_transaction_id: str | None = None


@dataclass(frozen=True)
class BrokerTradeClosure:
    trade_id: str
    units: int
    price: float | None
    realized_pl: float | None
    reason: str = ""
    occurred_at: datetime | None = None


@dataclass(frozen=True)
class BrokerTransaction:
    transaction_id: str
    kind: str
    order_id: str | None = None
    trade_id: str | None = None
    client_reference: str = ""
    pair: str | None = None
    units: int = 0
    price: float | None = None
    reason: str = ""
    occurred_at: datetime | None = None
    closed_trades: tuple[BrokerTradeClosure, ...] = ()


@dataclass(frozen=True)
class BrokerTransactionBatch:
    transactions: tuple[BrokerTransaction, ...]
    last_transaction_id: str | None = None


@dataclass(frozen=True)
class InstrumentTradingRules:
    pair: str
    minimum_trade_size: int
    maximum_order_units: int
    trade_units_precision: int


@runtime_checkable
class BrokerQueryPort(Protocol):
    def account_capabilities(self) -> AccountCapabilities: ...

    def transactions_since(self, transaction_id: str) -> BrokerTransactionBatch: ...

    def instrument_rules(self, pair: str) -> InstrumentTradingRules: ...

    def position(self, reference_id: str) -> PositionSnapshot | None: ...

    def order(self, order_id: str) -> PositionSnapshot | None: ...

    def trade(self, trade_id: str) -> PositionSnapshot | None: ...

    def pending_orders(self) -> list[PositionSnapshot]: ...

    def open_positions(self) -> list[PositionSnapshot]: ...
