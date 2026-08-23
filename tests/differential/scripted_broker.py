from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping

from ogami_oanda.application.ports.broker import (
    AccountCapabilities,
    BrokerTransactionBatch,
    InstrumentTradingRules,
    ExecutionResult,
    OrderSubmissionResult,
)
from ogami_oanda.domain.orders.models import BrokerOrderRequest
from ogami_oanda.domain.positions.models import (
    OrderState,
    PositionSnapshot,
    TradeState,
)


@dataclass(frozen=True)
class ScriptedStep:
    action: str
    accepted: bool = True
    reference_id: str | None = None
    message: str = ""
    exception: str | None = None


class ScriptedBroker:
    """Scenario-driven fake broker for current-runner differential replay."""

    def __init__(
        self,
        *,
        submit_steps: Iterable[ScriptedStep] = (),
        cancel_steps: Iterable[ScriptedStep] = (),
        close_steps: Iterable[ScriptedStep] = (),
        amend_steps: Iterable[ScriptedStep] = (),
        raw_steps: Iterable[Mapping[str, object]] | None = None,
    ) -> None:
        self.submit_steps = list(submit_steps)
        self.cancel_steps = list(cancel_steps)
        self.close_steps = list(close_steps)
        self.amend_steps = list(amend_steps)
        self.raw_steps = (
            [
                dict(step)
                for step in raw_steps
                if step.get("runner") in {None, "both", "current"}
            ]
            if raw_steps is not None
            else None
        )
        self.broker_actions: list[str] = []
        self.requests: list[BrokerOrderRequest] = []
        self.commands: list[tuple[str, tuple[object, ...]]] = []
        self.positions: dict[str, PositionSnapshot] = {}
        self.orders: dict[str, PositionSnapshot] = {}
        self.trades: dict[str, PositionSnapshot] = {}
        self.transactions = BrokerTransactionBatch((), "0")

    def account_capabilities(self) -> AccountCapabilities:
        return AccountCapabilities("id", True, self.transactions.last_transaction_id)

    def transactions_since(self, transaction_id: str) -> BrokerTransactionBatch:
        del transaction_id
        return self.transactions

    def instrument_rules(self, pair: str) -> InstrumentTradingRules:
        return InstrumentTradingRules(pair, 1, 1_000_000, 0)

    def submit(self, request: BrokerOrderRequest) -> OrderSubmissionResult:
        self.requests.append(request)
        raw = self._consume_raw_response("submit")
        if raw is not None:
            self._raise_raw_exception(raw)
            state = str(raw.get("state", "PENDING")).upper()
            if state == "PENDING":
                return OrderSubmissionResult.pending(str(raw["order_id"]))
            if state == "FILLED":
                return OrderSubmissionResult.filled(
                    order_id=(
                        str(raw["order_id"])
                        if raw.get("order_id") is not None
                        else None
                    ),
                    trade_id=str(raw["trade_id"]),
                    fill_price=(
                        float(raw["fill_price"])
                        if raw.get("fill_price") is not None
                        else None
                    ),
                )
            if state == "CANCELLED":
                return OrderSubmissionResult.cancelled(
                    str(raw.get("reason", "scripted cancellation")),
                    order_id=(
                        str(raw["order_id"])
                        if raw.get("order_id") is not None
                        else None
                    ),
                )
            if state == "UNKNOWN":
                return OrderSubmissionResult.unknown(
                    str(raw.get("reason", "scripted unknown outcome"))
                )
            if state == "TERMINAL":
                return OrderSubmissionResult.terminal(
                    str(raw.get("reason", "scripted terminal outcome")),
                    order_id=(
                        str(raw["order_id"])
                        if raw.get("order_id") is not None
                        else None
                    ),
                )
            if state == "REJECTED":
                return OrderSubmissionResult.rejected(
                    str(raw.get("reason", "scripted rejection"))
                )
            raise ValueError(f"Unsupported raw submit state: {state}")
        step = self._pop_step(self.submit_steps, "submit")
        if step.exception:
            raise RuntimeError(step.exception)
        if step.accepted:
            return OrderSubmissionResult.pending(
                step.reference_id or f"order-{len(self.requests)}"
            )
        return OrderSubmissionResult.rejected(step.message or "scripted rejection")

    def cancel_order(self, order_id: str) -> ExecutionResult:
        self.commands.append(("cancel_order", (order_id,)))
        raw = self._consume_raw_response("cancel_order")
        if raw is not None:
            return self._raw_execution_result(raw, order_id)
        step = self._pop_step(self.cancel_steps, "cancel_order")
        if step.exception:
            raise RuntimeError(step.exception)
        return ExecutionResult(
            accepted=step.accepted,
            reference_id=step.reference_id or order_id,
            message=step.message,
        )

    def close_trade(self, trade_id: str, units: int | None = None) -> ExecutionResult:
        self.commands.append(("close_trade", (trade_id, units)))
        raw = self._consume_raw_response("close_trade")
        if raw is not None:
            return self._raw_execution_result(raw, trade_id)
        step = self._pop_step(self.close_steps, "close_trade")
        if step.exception:
            raise RuntimeError(step.exception)
        return ExecutionResult(
            accepted=step.accepted,
            reference_id=step.reference_id or trade_id,
            message=step.message,
        )

    def amend_protection(self, trade_id: str, take_profit_price: float | None, stop_loss_price: float | None) -> ExecutionResult:
        self.commands.append(("amend_protection", (trade_id, take_profit_price, stop_loss_price)))
        raw = self._consume_raw_response("amend_protection")
        if raw is not None:
            return self._raw_execution_result(raw, trade_id)
        step = self._pop_step(self.amend_steps, "amend_protection")
        if step.exception:
            raise RuntimeError(step.exception)
        return ExecutionResult(
            accepted=step.accepted,
            reference_id=step.reference_id or trade_id,
            message=step.message,
        )

    def position(self, reference_id: str) -> PositionSnapshot | None:
        raw = self._consume_raw_response("position")
        if raw is not None:
            return self._raw_snapshot(raw, reference_id, query="position")
        return self.order(reference_id) or self.trade(reference_id) or self.positions.get(reference_id)

    def order(self, order_id: str) -> PositionSnapshot | None:
        raw = self._consume_raw_response("order")
        if raw is not None:
            return self._raw_snapshot(raw, order_id, query="order")
        return self.orders.get(order_id) or self.positions.get(order_id)

    def trade(self, trade_id: str) -> PositionSnapshot | None:
        raw = self._consume_raw_response("trade")
        if raw is not None:
            return self._raw_snapshot(raw, trade_id, query="trade")
        return self.trades.get(trade_id) or self.positions.get(trade_id)

    def pending_orders(self) -> list[PositionSnapshot]:
        return [snapshot for snapshot in self.orders.values() if snapshot.order_state.value == "PENDING"]

    def open_positions(self) -> list[PositionSnapshot]:
        return [snapshot for snapshot in self.positions.values() if snapshot.life]

    def assert_broker_steps_consumed(self) -> None:
        if self.raw_steps:
            actions = [str(step.get("action")) for step in self.raw_steps]
            raise ValueError(f"Scripted broker has unconsumed steps: {actions}")

    def _consume_raw_response(self, action: str) -> dict[str, Any] | None:
        if self.raw_steps is None:
            return None
        if not self.raw_steps:
            raise ValueError(f"Scripted broker step underflow for action {action}")
        step = self.raw_steps.pop(0)
        actual = str(step.get("action"))
        if actual != action:
            raise ValueError(
                f"Scripted broker action mismatch: expected {actual}, got {action}"
            )
        response = step.get("response")
        if not isinstance(response, Mapping):
            raise ValueError(f"Scripted broker {action} response must be an object")
        self.broker_actions.append(action)
        return dict(response)

    @staticmethod
    def _raise_raw_exception(response: Mapping[str, Any]) -> None:
        if response.get("exception") is not None:
            raise RuntimeError(str(response["exception"]))

    def _raw_execution_result(
        self,
        response: Mapping[str, Any],
        default_reference_id: str,
    ) -> ExecutionResult:
        self._raise_raw_exception(response)
        return ExecutionResult(
            accepted=bool(response.get("accepted", True)),
            reference_id=str(
                response.get("reference_id", default_reference_id)
            ),
            message=str(response.get("reason", response.get("message", ""))),
        )

    def _raw_snapshot(
        self,
        response: Mapping[str, Any],
        reference_id: str,
        *,
        query: str,
    ) -> PositionSnapshot | None:
        self._raise_raw_exception(response)
        if response.get("found", True) is False:
            return None
        raw_state = str(response.get("state", "PENDING")).upper()
        raw_trade_state = str(response.get("trade_state", "NONE")).upper()
        order_state = OrderState(raw_state)
        trade_state = TradeState(raw_trade_state)
        order_id = response.get("order_id")
        trade_id = response.get("trade_id")
        if query == "order" and order_id is None:
            order_id = reference_id
        if query == "trade" and trade_id is None:
            trade_id = reference_id
        return PositionSnapshot(
            name=str(response.get("name", "scripted-position")),
            pair=str(response.get("pair", "USD_JPY")),
            order_state=order_state,
            trade_state=trade_state,
            order_id=str(order_id) if order_id is not None else None,
            trade_id=str(trade_id) if trade_id is not None else None,
            life=bool(response.get("life", raw_state not in {"CANCELLED", "REJECTED"})),
            direction=(
                int(response["direction"])
                if response.get("direction") is not None
                else None
            ),
            target_price=(
                float(response["target_price"])
                if response.get("target_price") is not None
                else None
            ),
            units=int(response.get("units", 0)),
            current_stop_loss=(
                float(response["current_stop_loss"])
                if response.get("current_stop_loss") is not None
                else None
            ),
            current_price=(
                float(response["current_price"])
                if response.get("current_price") is not None
                else None
            ),
            unrealized_pl=float(response.get("unrealized_pl", 0.0)),
            realized_pl=float(response.get("realized_pl", 0.0)),
            elapsed_seconds=float(response.get("elapsed_seconds", 0.0)),
        )

    @staticmethod
    def _pop_step(queue: list[ScriptedStep], action: str) -> ScriptedStep:
        if queue:
            step = queue.pop(0)
            if step.action != action:
                raise ValueError(f"Expected scripted action {action}, got {step.action}")
            return step
        return ScriptedStep(action=action)
