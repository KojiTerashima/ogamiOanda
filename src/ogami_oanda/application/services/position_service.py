from __future__ import annotations

from dataclasses import dataclass

from ogami_oanda.application.ports.broker import BrokerExecutionPort, BrokerQueryPort
from ogami_oanda.application.ports.clock import Clock
from ogami_oanda.application.ports.notifications import Notifier
from ogami_oanda.application.ports.trade_history import TradeHistoryRepository
from ogami_oanda.application.services.closure_reporting_service import (
    ClosureReportingService,
)
from ogami_oanda.domain.orders.models import OrderPlan
from ogami_oanda.domain.positions.managed_position import ManagedPosition
from ogami_oanda.domain.positions.models import (
    PositionCommand,
    PositionEvent,
    PositionSnapshot,
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


class PositionService:
    def __init__(
        self,
        broker_execution: BrokerExecutionPort,
        broker_query: BrokerQueryPort,
        notifier: Notifier,
        history: TradeHistoryRepository,
        clock: Clock,
    ) -> None:
        self.broker_execution = broker_execution
        self.broker_query = broker_query
        self.notifier = notifier
        self.history = history
        self.clock = clock
        self.entry_confirmation = EntryConfirmationPolicy()
        self.stop_loss = StopLossPolicy()
        self.closure_reporting = ClosureReportingService(history, notifier)
        self._emitted_event_ids: set[str] = set()

    def register(self, position: ManagedPosition, order_plan: OrderPlan, submit: bool = True) -> ManagedPosition:
        position = position.with_order_plan(order_plan, self.clock.now())
        if not submit:
            return position.watching()
        result = self.broker_execution.submit(order_plan.broker_request)
        if not result.accepted or result.reference_id is None:
            self.notifier.send(f"Order rejected: {position.snapshot.name}", pair=position.snapshot.pair)
            return position.cancelled()
        self.notifier.send(f"Order submitted: {position.snapshot.name}", pair=position.snapshot.pair)
        return position.pending(result.reference_id)

    def sync(self, position: ManagedPosition) -> ManagedPosition:
        return self.sync_result(position).position

    def sync_result(
        self,
        position: ManagedPosition,
        *,
        current_price: float | None = None,
        dry_run: bool = False,
    ) -> PositionSyncResult:
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
            timeout = self._trade_timeout(opened, broker_snapshot, dry_run)
            if timeout is not None:
                events = () if was_open else self._events_once(self._event("trade_opened", opened, broker_snapshot), dry_run)
                return PositionSyncResult(timeout.position, timeout.commands, events, timeout.reason)
            amendment = self._stop_loss_amendment(opened, current_price, dry_run)
            opened = amendment.position
            events = () if was_open else self._events_once(self._event("trade_opened", opened, broker_snapshot), dry_run)
            return PositionSyncResult(opened, amendment.commands, events, amendment.reason)
        return PositionSyncResult(position)

    def close(self, position: ManagedPosition) -> ManagedPosition:
        trade_id = position.snapshot.trade_id
        if trade_id is None:
            return position.cancelled()
        result = self.broker_execution.close_trade(trade_id)
        if not result.accepted:
            return position
        closed = position.closed()
        broker_snapshot = PositionSnapshot(
            closed.snapshot.name,
            closed.snapshot.pair,
            closed.snapshot.order_state,
            closed.snapshot.trade_state,
            order_id=closed.snapshot.order_id,
            trade_id=trade_id,
            direction=closed.runtime.direction,
            target_price=closed.runtime.target_price,
            units=closed.runtime.order_plan.intent.units if closed.runtime.order_plan else 0,
            average_close_price=closed.runtime.target_price,
        )
        self.closure_reporting.report(self._event("trade_closed", closed, broker_snapshot))
        return closed

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
        result = self.broker_execution.submit(plan.broker_request)
        if not result.accepted or result.reference_id is None:
            return PositionSyncResult(updated.cancelled(), commands=(command,), reason="broker_rejected")
        pending = updated.pending(result.reference_id)
        return PositionSyncResult(
            pending,
            commands=(command,),
            events=self._events_once(self._event("order_submitted", pending, pending.snapshot), False),
            reason=decision.reason,
        )

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
        policy = ExitPolicy(plan.intent.trade_timeout_min, plan.intent.order_timeout_min)
        if not policy.should_cancel_order(broker_snapshot, elapsed):
            return None
        order_id = position.snapshot.order_id
        command = PositionCommand("cancel_order", order_id, "order_timeout")
        if dry_run or order_id is None:
            return PositionSyncResult(position, commands=(command,), reason="dry_run" if dry_run else "missing_order_id")
        result = self.broker_execution.cancel_order(order_id)
        if not result.accepted:
            return PositionSyncResult(position, commands=(command,), reason="cancel_rejected")
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
        policy = ExitPolicy(plan.intent.trade_timeout_min, plan.intent.order_timeout_min, enabled)
        if not policy.should_close(broker_snapshot, elapsed):
            return None
        trade_id = position.snapshot.trade_id
        command = PositionCommand("close_trade", trade_id, "trade_timeout")
        if dry_run or trade_id is None:
            return PositionSyncResult(position, commands=(command,), reason="dry_run" if dry_run else "missing_trade_id")
        result = self.broker_execution.close_trade(trade_id)
        if not result.accepted:
            return PositionSyncResult(position, commands=(command,), reason="close_rejected")
        return PositionSyncResult(
            position.with_runtime(close_requested=True),
            commands=(command,),
            reason="trade_timeout",
        )

    def _stop_loss_amendment(
        self,
        position: ManagedPosition,
        current_price: float | None,
        dry_run: bool,
    ) -> PositionSyncResult:
        plan = position.runtime.order_plan
        trade_id = position.snapshot.trade_id
        current_stop = position.runtime.current_stop_loss
        if plan is None or trade_id is None or current_price is None or current_stop is None:
            return PositionSyncResult(position, reason="open")
        filled_at = position.runtime.filled_at or self.clock.now()
        elapsed = (self.clock.now() - filled_at).total_seconds()
        applied = {position.runtime.applied_lc_change_index} if position.runtime.applied_lc_change_index >= 0 else set()
        amendment = self.stop_loss.next_amendment(
            plan.intent.lc_change,
            position.runtime.target_price,
            position.runtime.direction,
            current_price,
            current_stop,
            elapsed,
            applied,
        )
        if amendment is None:
            return PositionSyncResult(position, reason="open")
        command = PositionCommand("amend_stop_loss", trade_id, "lc_trigger", amendment.stop_loss_price)
        if dry_run:
            return PositionSyncResult(position, commands=(command,), reason="dry_run")
        result = self.broker_execution.amend_protection(trade_id, None, amendment.stop_loss_price)
        if not result.accepted:
            return PositionSyncResult(position, commands=(command,), reason="amend_rejected")
        amended = position.with_runtime(
            current_stop_loss=amendment.stop_loss_price,
            applied_lc_change_index=amendment.rule_index,
        )
        return PositionSyncResult(amended, commands=(command,), reason="lc_amended")

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
        return position.with_runtime(
            unrealized_pl=unrealized,
            realized_pl=broker_snapshot.realized_pl,
            max_unrealized_pl=max(position.runtime.max_unrealized_pl, unrealized),
            min_unrealized_pl=min(position.runtime.min_unrealized_pl, unrealized),
        )
