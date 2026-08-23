from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from ogami_oanda.application.ports.broker import (
    AccountCapabilities,
    ExecutionResult,
    OrderSubmissionResult,
)
from ogami_oanda.domain.orders.models import BrokerOrderRequest
from ogami_oanda.domain.positions.models import PositionSnapshot


@dataclass(frozen=True)
class ScriptedStep:
    action: str
    accepted: bool = True
    reference_id: str | None = None
    message: str = ""


class ScriptedBroker:
    """Scenario-driven fake broker for current-runner differential replay."""

    def __init__(
        self,
        *,
        submit_steps: Iterable[ScriptedStep] = (),
        cancel_steps: Iterable[ScriptedStep] = (),
        close_steps: Iterable[ScriptedStep] = (),
        amend_steps: Iterable[ScriptedStep] = (),
    ) -> None:
        self.submit_steps = list(submit_steps)
        self.cancel_steps = list(cancel_steps)
        self.close_steps = list(close_steps)
        self.amend_steps = list(amend_steps)
        self.requests: list[BrokerOrderRequest] = []
        self.commands: list[tuple[str, tuple[object, ...]]] = []
        self.positions: dict[str, PositionSnapshot] = {}
        self.orders: dict[str, PositionSnapshot] = {}
        self.trades: dict[str, PositionSnapshot] = {}

    def account_capabilities(self) -> AccountCapabilities:
        return AccountCapabilities("id", True)

    def submit(self, request: BrokerOrderRequest) -> OrderSubmissionResult:
        self.requests.append(request)
        step = self._pop_step(self.submit_steps, "submit")
        if step.accepted:
            return OrderSubmissionResult.pending(
                step.reference_id or f"order-{len(self.requests)}"
            )
        return OrderSubmissionResult.rejected(step.message or "scripted rejection")

    def cancel_order(self, order_id: str) -> ExecutionResult:
        self.commands.append(("cancel_order", (order_id,)))
        step = self._pop_step(self.cancel_steps, "cancel_order")
        return ExecutionResult(
            accepted=step.accepted,
            reference_id=step.reference_id or order_id,
            message=step.message,
        )

    def close_trade(self, trade_id: str, units: int | None = None) -> ExecutionResult:
        self.commands.append(("close_trade", (trade_id, units)))
        step = self._pop_step(self.close_steps, "close_trade")
        return ExecutionResult(
            accepted=step.accepted,
            reference_id=step.reference_id or trade_id,
            message=step.message,
        )

    def amend_protection(self, trade_id: str, take_profit_price: float | None, stop_loss_price: float | None) -> ExecutionResult:
        self.commands.append(("amend_protection", (trade_id, take_profit_price, stop_loss_price)))
        step = self._pop_step(self.amend_steps, "amend_protection")
        return ExecutionResult(
            accepted=step.accepted,
            reference_id=step.reference_id or trade_id,
            message=step.message,
        )

    def position(self, reference_id: str) -> PositionSnapshot | None:
        return self.order(reference_id) or self.trade(reference_id) or self.positions.get(reference_id)

    def order(self, order_id: str) -> PositionSnapshot | None:
        return self.orders.get(order_id) or self.positions.get(order_id)

    def trade(self, trade_id: str) -> PositionSnapshot | None:
        return self.trades.get(trade_id) or self.positions.get(trade_id)

    def pending_orders(self) -> list[PositionSnapshot]:
        return [snapshot for snapshot in self.orders.values() if snapshot.order_state.value == "PENDING"]

    def open_positions(self) -> list[PositionSnapshot]:
        return [snapshot for snapshot in self.positions.values() if snapshot.life]

    @staticmethod
    def _pop_step(queue: list[ScriptedStep], action: str) -> ScriptedStep:
        if queue:
            step = queue.pop(0)
            if step.action != action:
                raise ValueError(f"Expected scripted action {action}, got {step.action}")
            return step
        return ScriptedStep(action=action)
