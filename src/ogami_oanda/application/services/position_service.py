from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Callable, Mapping

from ogami_oanda.application.ports.broker import BrokerExecutionPort, BrokerQueryPort
from ogami_oanda.application.ports.broker import (
    MutationState,
    OrderSubmissionResult,
    OrderSubmissionState,
)
from ogami_oanda.application.ports.position_state import PendingBrokerMutation
from ogami_oanda.application.ports.clock import Clock
from ogami_oanda.application.ports.notifications import Notifier
from ogami_oanda.application.ports.trade_history import TradeHistoryRepository
from ogami_oanda.application.services.closure_reporting_service import (
    ClosureReportingService,
)
from ogami_oanda.domain.orders.models import OrderPlan
from ogami_oanda.domain.positions.managed_position import ManagedPosition
from ogami_oanda.domain.positions.models import (
    OrderState,
    PositionCommand,
    PositionEvent,
    PositionSnapshot,
    SubmissionPhase,
)
from ogami_oanda.strategy.position_management import (
    EntryAction,
    EntryConfirmationPolicy,
    EntryConfirmationState,
    ExitPolicy,
    StopLossPolicy,
)


@dataclass(frozen=True)
class PositionSyncResult:
    position: ManagedPosition
    commands: tuple[PositionCommand, ...] = ()
    events: tuple[PositionEvent, ...] = ()
    reason: str = "unchanged"


@dataclass(frozen=True)
class CandleStopLossInput:
    """Completed-candle data used by the legacy candle stop-loss rule."""

    latest_peak: Mapping[str, object]
    previous_candle: Mapping[str, object]


class PositionService:
    def __init__(
        self,
        broker_execution: BrokerExecutionPort,
        broker_query: BrokerQueryPort,
        notifier: Notifier,
        history: TradeHistoryRepository,
        clock: Clock,
        *,
        entry_confirmation: EntryConfirmationPolicy | None = None,
        stop_loss: StopLossPolicy | None = None,
        exit_policy_factory: Callable[[int, int, bool], ExitPolicy] = ExitPolicy,
    ) -> None:
        self.broker_execution = broker_execution
        self.broker_query = broker_query
        self.notifier = notifier
        self.history = history
        self.clock = clock
        self.entry_confirmation = entry_confirmation or EntryConfirmationPolicy()
        self.stop_loss = stop_loss or StopLossPolicy()
        self.exit_policy_factory = exit_policy_factory
        self.closure_reporting = ClosureReportingService(history, notifier)
        self._emitted_event_ids: set[str] = set()
        self._before_mutation: Callable[[PendingBrokerMutation], None] = lambda _mutation: None
        self._complete_mutation: Callable[[bool], None] = lambda _unknown: None

    def set_mutation_hooks(
        self,
        before_mutation: Callable[[PendingBrokerMutation], None],
        complete_mutation: Callable[[bool], None],
    ) -> None:
        self._before_mutation = before_mutation
        self._complete_mutation = complete_mutation

    def register(self, position: ManagedPosition, order_plan: OrderPlan, submit: bool = True) -> ManagedPosition:
        position = self.prepare(position, order_plan)
        if not submit:
            return position.watching()
        return self.submit_prepared(position)

    def prepare(
        self,
        position: ManagedPosition,
        order_plan: OrderPlan,
    ) -> ManagedPosition:
        return position.with_order_plan(order_plan, self.clock.now())

    def submit_prepared(
        self,
        position: ManagedPosition,
        *,
        journal: bool = True,
    ) -> ManagedPosition:
        order_plan = position.runtime.order_plan
        if order_plan is None:
            raise ValueError("prepared position requires an order plan")
        if journal:
            self._start_mutation("submit_order", position, None, "entry_submit")
        result = self.broker_execution.submit(order_plan.broker_request)
        if journal:
            self._complete_mutation(result.state is OrderSubmissionState.UNKNOWN)
        return self._apply_submission_result(position, result)

    def sync(self, position: ManagedPosition) -> ManagedPosition:
        return self.sync_result(position).position

    def sync_result(
        self,
        position: ManagedPosition,
        *,
        current_price: float | None = None,
        candle_stop_loss: CandleStopLossInput | None = None,
        dry_run: bool = False,
    ) -> PositionSyncResult:
        if position.snapshot.order_state is OrderState.SUBMISSION_UNCERTAIN:
            return PositionSyncResult(position, reason="submission_uncertain")
        if position.snapshot.waiting_order:
            return self._sync_watching(position, current_price, dry_run)
        if position.snapshot.trade_id is not None:
            broker_snapshot = self.broker_query.trade(position.snapshot.trade_id)
        elif position.snapshot.order_id is not None:
            broker_snapshot = self.broker_query.order(position.snapshot.order_id)
        else:
            return PositionSyncResult(position, reason="missing_broker_reference")
        if broker_snapshot is None:
            return PositionSyncResult(position, reason="broker_snapshot_missing")
        if broker_snapshot.order_state.value in {"CANCELLED", "REJECTED"}:
            cancelled = position.cancelled()
            event = self._event("order_cancelled", cancelled, broker_snapshot)
            return PositionSyncResult(
                cancelled,
                events=self._events_once(event, dry_run),
                reason="broker_cancelled",
            )
        if broker_snapshot.trade_state.value == "CLOSED":
            closed = self._with_broker_runtime(position, broker_snapshot).closed()
            event = self._event("trade_closed", closed, broker_snapshot)
            events = self._events_once(event, dry_run)
            if not dry_run and events:
                self.closure_reporting.report(event)
            return PositionSyncResult(closed, events=events, reason="broker_closed")
        timeout_result = self._pending_timeout(position, broker_snapshot, dry_run)
        if timeout_result is not None:
            return timeout_result
        if broker_snapshot.trade_id and broker_snapshot.trade_state.value == "OPEN":
            was_open = position.snapshot.trade_state.value == "OPEN"
            opened = self._with_broker_runtime(
                position.filled(broker_snapshot.trade_id, self.clock.now()),
                broker_snapshot,
            )
            if current_price is not None:
                opened = replace(
                    opened,
                    snapshot=replace(
                        opened.snapshot,
                        current_price=float(current_price),
                    ),
                )
            timeout = self._trade_timeout(opened, broker_snapshot, dry_run)
            if timeout is not None:
                events = () if was_open else self._events_once(self._event("trade_opened", opened, broker_snapshot), dry_run)
                return PositionSyncResult(timeout.position, timeout.commands, events, timeout.reason)
            amendment = self._stop_loss_amendment(
                opened,
                current_price,
                candle_stop_loss,
                dry_run,
            )
            opened = amendment.position
            events = () if was_open else self._events_once(self._event("trade_opened", opened, broker_snapshot), dry_run)
            return PositionSyncResult(opened, amendment.commands, events, amendment.reason)
        return PositionSyncResult(position)

    def close(
        self,
        position: ManagedPosition,
        *,
        dry_run: bool = False,
    ) -> ManagedPosition:
        trade_id = position.snapshot.trade_id
        if trade_id is None:
            return position.cancelled()
        if dry_run:
            return position
        self._start_mutation("close_trade", position, trade_id, "direct_close")
        result = self.broker_execution.close_trade(trade_id)
        self._complete_mutation(result.state is MutationState.UNKNOWN)
        if not result.accepted:
            return position
        # OANDA's close acknowledgement is not the authoritative trade result.
        # Keep the position alive until a subsequent query returns its CLOSED
        # snapshot with the actual close price and realized P/L.
        return position.with_runtime(close_requested=True)

    def _sync_watching(
        self,
        position: ManagedPosition,
        current_price: float | None,
        dry_run: bool,
    ) -> PositionSyncResult:
        plan = position.runtime.order_plan
        if plan is None or position.runtime.registered_at is None or current_price is None:
            return PositionSyncResult(position, reason="watching_input_missing")
        state = EntryConfirmationState(
            position.runtime.registered_at,
            position.runtime.watch_step1_started_at,
            position.runtime.watch_step2_started_at,
            position.runtime.watch_step1_over_price,
        )
        decision = self.entry_confirmation.decide(
            plan.intent.order_type.value,
            position.runtime.direction,
            position.runtime.target_price,
            current_price,
            self.clock.now(),
            plan.intent.order_timeout_min,
            state,
        )
        updated = position.with_runtime(
            watch_step1_started_at=decision.state.step1_started_at,
            watch_step2_started_at=decision.state.step2_started_at,
            watch_step1_over_price=decision.state.step1_over_price,
        )
        if decision.action is EntryAction.WAIT:
            return PositionSyncResult(updated, reason=decision.reason)
        action = "submit_order" if decision.action is EntryAction.SUBMIT else "cancel_watching"
        command = PositionCommand(action, position.snapshot.name, decision.reason, data={"broker_request": plan.broker_request})
        if dry_run:
            return PositionSyncResult(position, commands=(command,), reason="dry_run")
        if decision.action is EntryAction.CANCEL:
            cancelled = updated.cancelled()
            return PositionSyncResult(
                cancelled,
                commands=(command,),
                events=self._events_once(self._event("order_cancelled", cancelled, cancelled.snapshot), False),
                reason=decision.reason,
            )
        self._start_mutation(
            "submit_order",
            updated,
            None,
            decision.reason,
        )
        result = self.broker_execution.submit(plan.broker_request)
        self._complete_mutation(result.state is OrderSubmissionState.UNKNOWN)
        submitted = self._apply_submission_result(updated, result)
        if submitted.snapshot.order_state is OrderState.SUBMISSION_UNCERTAIN:
            return PositionSyncResult(submitted, commands=(command,), reason="submission_uncertain")
        if not result.accepted:
            return PositionSyncResult(submitted, commands=(command,), reason=result.reason or "broker_rejected")
        event_kind = "trade_opened" if result.state is OrderSubmissionState.FILLED else "order_submitted"
        return PositionSyncResult(
            submitted,
            commands=(command,),
            events=self._events_once(self._event(event_kind, submitted, submitted.snapshot), False),
            reason=decision.reason,
        )

    def _apply_submission_result(
        self,
        position: ManagedPosition,
        result: OrderSubmissionResult,
    ) -> ManagedPosition:
        if result.state is OrderSubmissionState.PENDING and result.order_id is not None:
            self.notifier.send(
                f"Order submitted: {position.snapshot.name}",
                pair=position.snapshot.pair,
            )
            return position.pending(result.order_id)
        if result.state is OrderSubmissionState.FILLED and result.trade_id is not None:
            self.notifier.send(
                f"Order filled: {position.snapshot.name}",
                pair=position.snapshot.pair,
            )
            return position.filled(
                result.trade_id,
                self.clock.now(),
                order_id=result.order_id,
                fill_price=result.fill_price,
            )
        if result.state is OrderSubmissionState.UNKNOWN:
            reason = result.reason or "request outcome unknown"
            self.notifier.send(
                f"Order submission uncertain: {position.snapshot.name}: {reason}",
                pair=position.snapshot.pair,
            )
            return position.submission_uncertain(reason)
        reason = result.reason or result.state.value
        self.notifier.send(
            f"Order rejected: {position.snapshot.name}: {reason}",
            pair=position.snapshot.pair,
        )
        if result.state is OrderSubmissionState.CANCELLED:
            return position.cancelled().with_runtime(submission_reason=reason)
        if result.state is OrderSubmissionState.TERMINAL:
            return position.rejected(reason).with_runtime(
                submission_phase=SubmissionPhase.TERMINAL,
            )
        return position.rejected(reason)

    def _pending_timeout(
        self,
        position: ManagedPosition,
        broker_snapshot: PositionSnapshot,
        dry_run: bool,
    ) -> PositionSyncResult | None:
        plan = position.runtime.order_plan
        if plan is None or position.runtime.registered_at is None:
            return None
        elapsed = (self.clock.now() - position.runtime.registered_at).total_seconds()
        policy = self.exit_policy_factory(plan.intent.trade_timeout_min, plan.intent.order_timeout_min, False)
        if not policy.should_cancel_order(broker_snapshot, elapsed):
            return None
        order_id = position.snapshot.order_id
        command = PositionCommand("cancel_order", order_id, "order_timeout")
        if dry_run or order_id is None:
            return PositionSyncResult(position, commands=(command,), reason="dry_run" if dry_run else "missing_order_id")
        self._start_mutation("cancel_order", position, order_id, "order_timeout")
        result = self.broker_execution.cancel_order(order_id)
        self._complete_mutation(result.state is MutationState.UNKNOWN)
        if not result.accepted:
            reason = "cancel_unknown" if result.state is MutationState.UNKNOWN else "cancel_rejected"
            return PositionSyncResult(position, commands=(command,), reason=reason)
        cancelled = position.cancelled()
        return PositionSyncResult(
            cancelled,
            commands=(command,),
            events=self._events_once(self._event("order_cancelled", cancelled, broker_snapshot), False),
            reason="order_timeout",
        )

    def _trade_timeout(
        self,
        position: ManagedPosition,
        broker_snapshot: PositionSnapshot,
        dry_run: bool,
    ) -> PositionSyncResult | None:
        plan = position.runtime.order_plan
        if plan is None or position.runtime.filled_at is None or position.runtime.close_requested:
            return None
        elapsed = (self.clock.now() - position.runtime.filled_at).total_seconds()
        enabled = bool(plan.intent.metadata.get("trade_timeout_enabled", False))
        policy = self.exit_policy_factory(plan.intent.trade_timeout_min, plan.intent.order_timeout_min, enabled)
        if not policy.should_close(broker_snapshot, elapsed):
            return None
        trade_id = position.snapshot.trade_id
        command = PositionCommand("close_trade", trade_id, "trade_timeout")
        if dry_run or trade_id is None:
            return PositionSyncResult(position, commands=(command,), reason="dry_run" if dry_run else "missing_trade_id")
        self._start_mutation("close_trade", position, trade_id, "trade_timeout")
        result = self.broker_execution.close_trade(trade_id)
        self._complete_mutation(result.state is MutationState.UNKNOWN)
        if not result.accepted:
            reason = "close_unknown" if result.state is MutationState.UNKNOWN else "close_rejected"
            return PositionSyncResult(position, commands=(command,), reason=reason)
        return PositionSyncResult(
            position.with_runtime(close_requested=True),
            commands=(command,),
            reason="trade_timeout",
        )

    def _stop_loss_amendment(
        self,
        position: ManagedPosition,
        current_price: float | None,
        candle_stop_loss: CandleStopLossInput | None,
        dry_run: bool,
    ) -> PositionSyncResult:
        plan = position.runtime.order_plan
        trade_id = position.snapshot.trade_id
        current_stop = position.runtime.current_stop_loss
        if (
            plan is None
            or trade_id is None
            or current_price is None
            or current_stop is None
            or position.runtime.close_requested
        ):
            return PositionSyncResult(position, reason="open")
        filled_at = position.runtime.filled_at or self.clock.now()
        elapsed = (self.clock.now() - filled_at).total_seconds()
        rule_index: int | None = None
        reason = "lc_trigger"
        stop_loss_price: float | None = None
        if not position.runtime.candle_stop_loss_done:
            applied = (
                {position.runtime.applied_lc_change_index}
                if position.runtime.applied_lc_change_index >= 0
                else set()
            )
            amendment = self.stop_loss.next_amendment(
                plan.intent.lc_change,
                position.runtime.target_price,
                position.runtime.direction,
                current_price,
                current_stop,
                elapsed,
                applied,
            )
            if amendment is not None:
                rule_index = amendment.rule_index
                stop_loss_price = amendment.stop_loss_price
        if stop_loss_price is None and candle_stop_loss is not None:
            stop_loss_price = self.stop_loss.candle_amendment(
                position.runtime.target_price,
                position.runtime.direction,
                current_stop,
                elapsed,
                candle_stop_loss.latest_peak,
                candle_stop_loss.previous_candle,
                self.clock.now(),
                enabled=bool(plan.intent.metadata.get("candle_lc_enabled", True)),
                already_done=position.runtime.candle_stop_loss_done,
            )
            reason = "candle_lc_trigger"
        if stop_loss_price is None:
            return PositionSyncResult(position, reason="open")
        command = PositionCommand(
            "amend_stop_loss",
            trade_id,
            reason,
            stop_loss_price,
        )
        if dry_run:
            return PositionSyncResult(position, commands=(command,), reason="dry_run")
        self._start_mutation(
            "amend_stop_loss",
            position,
            trade_id,
            reason,
            stop_loss_price=stop_loss_price,
            applied_lc_change_index=rule_index,
            candle_stop_loss_done=rule_index is None,
        )
        result = self.broker_execution.amend_protection(
            trade_id,
            None,
            stop_loss_price,
        )
        self._complete_mutation(result.state is MutationState.UNKNOWN)
        if not result.accepted:
            result_reason = "amend_unknown" if result.state is MutationState.UNKNOWN else "amend_rejected"
            return PositionSyncResult(position, commands=(command,), reason=result_reason)
        changes: dict[str, object] = {"current_stop_loss": stop_loss_price}
        if rule_index is None:
            changes["candle_stop_loss_done"] = True
        else:
            changes["applied_lc_change_index"] = rule_index
        amended = position.with_runtime(**changes)
        result_reason = "candle_lc_amended" if rule_index is None else "lc_amended"
        return PositionSyncResult(amended, commands=(command,), reason=result_reason)

    def _start_mutation(
        self,
        action: str,
        position: ManagedPosition,
        broker_reference_id: str | None,
        reason: str,
        *,
        stop_loss_price: float | None = None,
        applied_lc_change_index: int | None = None,
        candle_stop_loss_done: bool | None = None,
    ) -> None:
        plan = position.runtime.order_plan
        client_reference = (
            plan.broker_request.client_reference if plan is not None else ""
        )
        self._before_mutation(
            PendingBrokerMutation(
                action=action,
                position_name=position.snapshot.name,
                client_reference=client_reference,
                broker_reference_id=broker_reference_id,
                reason=reason,
                stop_loss_price=stop_loss_price,
                applied_lc_change_index=applied_lc_change_index,
                candle_stop_loss_done=candle_stop_loss_done,
                prepared_at=self.clock.now(),
            )
        )

    def _event(
        self,
        kind: str,
        position: ManagedPosition,
        broker_snapshot: PositionSnapshot,
    ) -> PositionEvent:
        reference = broker_snapshot.trade_id or broker_snapshot.order_id or position.snapshot.name
        return PositionEvent(
            f"{kind}:{reference}",
            kind,
            position.snapshot.name,
            position.snapshot.pair,
            self.clock.now(),
            {"position": position, "broker_snapshot": broker_snapshot},
        )

    def _events_once(self, event: PositionEvent, dry_run: bool) -> tuple[PositionEvent, ...]:
        if event.event_id in self._emitted_event_ids:
            return ()
        if not dry_run:
            self._emitted_event_ids.add(event.event_id)
        return (event,)

    @staticmethod
    def _with_broker_runtime(
        position: ManagedPosition,
        broker_snapshot: PositionSnapshot,
    ) -> ManagedPosition:
        unrealized = broker_snapshot.unrealized_pl
        snapshot = replace(
            position.snapshot,
            order_state=broker_snapshot.order_state,
            trade_state=broker_snapshot.trade_state,
            order_id=broker_snapshot.order_id or position.snapshot.order_id,
            trade_id=broker_snapshot.trade_id or position.snapshot.trade_id,
            direction=broker_snapshot.direction
            if broker_snapshot.direction is not None
            else position.runtime.direction,
            target_price=broker_snapshot.target_price
            if broker_snapshot.target_price is not None
            else position.runtime.target_price,
            units=broker_snapshot.units or position.snapshot.units,
            source=broker_snapshot.source or position.runtime.source,
            line_strategy=broker_snapshot.line_strategy
            or position.runtime.line_strategy,
            current_stop_loss=broker_snapshot.current_stop_loss
            if broker_snapshot.current_stop_loss is not None
            else position.runtime.current_stop_loss,
            current_price=broker_snapshot.current_price
            if broker_snapshot.current_price is not None
            else position.snapshot.current_price,
            unrealized_pl=broker_snapshot.unrealized_pl,
            realized_pl=broker_snapshot.realized_pl,
            open_time=broker_snapshot.open_time or position.snapshot.open_time,
            close_time=broker_snapshot.close_time or position.snapshot.close_time,
            elapsed_seconds=broker_snapshot.elapsed_seconds
            or position.snapshot.elapsed_seconds,
            average_close_price=broker_snapshot.average_close_price
            if broker_snapshot.average_close_price is not None
            else position.snapshot.average_close_price,
            client_reference=broker_snapshot.client_reference
            or position.snapshot.client_reference,
        )
        updated = replace(position, snapshot=snapshot)
        return updated.with_runtime(
            direction=broker_snapshot.direction
            if broker_snapshot.direction is not None
            else position.runtime.direction,
            target_price=broker_snapshot.target_price
            if broker_snapshot.target_price is not None
            else position.runtime.target_price,
            current_stop_loss=broker_snapshot.current_stop_loss
            if broker_snapshot.current_stop_loss is not None
            else position.runtime.current_stop_loss,
            unrealized_pl=unrealized,
            realized_pl=broker_snapshot.realized_pl,
            max_unrealized_pl=max(position.runtime.max_unrealized_pl, unrealized),
            min_unrealized_pl=min(position.runtime.min_unrealized_pl, unrealized),
        )
