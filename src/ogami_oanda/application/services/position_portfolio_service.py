from __future__ import annotations

from dataclasses import dataclass, replace

from ogami_oanda.application.ports.broker import BrokerExecutionPort, BrokerQueryPort
from ogami_oanda.application.services.portfolio import ActiveOrder, Portfolio
from ogami_oanda.application.services.position_service import PositionService
from ogami_oanda.domain.market.currency_pair import currency_pair
from ogami_oanda.domain.orders.models import OrderPlan
from ogami_oanda.domain.positions.managed_position import ManagedPosition
from ogami_oanda.domain.positions.models import (
    PositionCommand,
    PositionEvent,
    PositionSnapshot,
)
from ogami_oanda.infrastructure.config.models import TradingSettings
from ogami_oanda.strategy.position_management import (
    HedgePolicy,
    HedgePosition,
    LinkagePolicy,
    LinkedPosition,
)


@dataclass(frozen=True)
class RegistrationResult:
    accepted: tuple[str, ...]
    rejected: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class PortfolioSummary:
    watching: int
    pending: int
    open: int
    closed: int
    commands: tuple[PositionCommand, ...] = ()
    events: tuple[PositionEvent, ...] = ()
    close_events: tuple[PositionEvent, ...] = ()


class PositionPortfolioService:
    def __init__(self, pair: str, position_service: PositionService, broker_query: BrokerQueryPort, broker_execution: BrokerExecutionPort, settings: TradingSettings = TradingSettings()) -> None:
        self.pair = pair
        self.position_service = position_service
        self.broker_query = broker_query
        self.broker_execution = broker_execution
        self.settings = settings
        self.slots: list[ManagedPosition | None] = [None] * settings.max_positions
        self.linkage_policy = LinkagePolicy(currency_pair(pair).round_keta)
        self.hedge_policy = HedgePolicy()

    def register_plans(self, plans: list[OrderPlan], submit: bool = True) -> RegistrationResult:
        accepted: list[str] = []
        rejected: list[tuple[str, str]] = []
        batch_orders = self._active_orders()
        candidates: list[OrderPlan] = []
        sorted_plans = sorted(
            plans,
            key=lambda plan: abs(currency_pair(self.pair).price_to_pips(plan.target_price - plan.context.current_price)),
        )
        for plan in sorted_plans:
            intent = plan.intent
            if intent.pair != self.pair:
                rejected.append((intent.name, "pair_mismatch"))
                continue
            if self._is_duplicate(plan, batch_orders):
                rejected.append((intent.name, "duplicate"))
                continue
            candidates.append(plan)
            batch_orders.append(
                ActiveOrder(
                    intent.name,
                    intent.direction.value,
                    plan.target_price,
                    intent.metadata.get("source"),
                    intent.metadata.get("line_strategy"),
                )
            )

        overfull_tiers = {
            tier
            for tier in {self._priority_tier(plan.intent.priority) for plan in candidates}
            if sum(self._priority_tier(plan.intent.priority) == tier for plan in candidates) > self._available_slot_count(tier)
        }
        accepted_candidates = []
        for plan in candidates:
            if self._priority_tier(plan.intent.priority) in overfull_tiers:
                rejected.append((plan.intent.name, "tier_full"))
            else:
                accepted_candidates.append(plan)

        for plan in accepted_candidates:
            intent = plan.intent
            slot_index = self._first_empty_slot(intent.priority)
            if slot_index is None:
                rejected.append((intent.name, "tier_full"))
                continue
            position = ManagedPosition.registered(intent.name, self.pair)
            position = self.position_service.register(position, plan, submit=submit)
            if position.snapshot.life:
                self.slots[slot_index] = position
                accepted.append(intent.name)
            else:
                rejected.append((intent.name, "broker_rejected"))
        return RegistrationResult(tuple(accepted), tuple(rejected))

    def sync_all(
        self,
        *,
        current_price: float | None = None,
        dry_run: bool = False,
    ) -> PortfolioSummary:
        working_slots = list(self.slots)
        commands: list[PositionCommand] = []
        events: list[PositionEvent] = []
        for index, position in enumerate(self.slots):
            if position is not None and position.snapshot.life:
                result = self.position_service.sync_result(
                    position,
                    current_price=current_price,
                    dry_run=dry_run,
                )
                working_slots[index] = result.position
                commands.extend(result.commands)
                events.extend(result.events)

        linkage_commands, linkage_events = self._apply_linkage(
            working_slots,
            tuple(events),
            dry_run,
        )
        commands.extend(linkage_commands)
        events.extend(linkage_events)
        commands.extend(self._apply_hedge(working_slots, dry_run))
        if not dry_run:
            self.slots = working_slots
        summary = self.summary()
        event_tuple = tuple(events)
        return replace(
            summary,
            commands=tuple(commands),
            events=event_tuple,
            close_events=tuple(event for event in event_tuple if event.kind == "trade_closed"),
        )

    def restore_open_positions(self) -> tuple[str, ...]:
        restored: list[str] = []
        for snapshot in self.broker_query.open_positions():
            if snapshot.pair != self.pair or not snapshot.life:
                continue
            index = self._first_empty_global_slot()
            if index is None:
                break
            self.slots[index] = ManagedPosition.restored(snapshot)
            restored.append(snapshot.name)
        return tuple(restored)

    def cancel_pending_on_start(self, enabled: bool) -> tuple[str, ...]:
        if not enabled:
            return ()
        cancelled = []
        for snapshot in self.broker_query.pending_orders():
            if snapshot.pair == self.pair and snapshot.order_id is not None:
                result = self.broker_execution.cancel_order(snapshot.order_id)
                if result.accepted:
                    cancelled.append(snapshot.order_id)
        return tuple(cancelled)

    def summary(self) -> PortfolioSummary:
        positions = [slot.snapshot for slot in self.slots if slot is not None]
        return PortfolioSummary(
            watching=sum(snapshot.waiting_order for snapshot in positions),
            pending=sum(snapshot.order_state.value == "PENDING" for snapshot in positions),
            open=sum(snapshot.trade_state.value == "OPEN" for snapshot in positions),
            closed=sum(not snapshot.life for snapshot in positions),
        )

    def _active_orders(self) -> list[ActiveOrder]:
        return [
            ActiveOrder(
                slot.snapshot.name,
                slot.runtime.direction,
                slot.runtime.target_price,
                slot.runtime.source,
                slot.runtime.line_strategy,
            )
            for slot in self.slots
            if slot is not None and slot.snapshot.life and slot.runtime.direction in {-1, 1}
        ]

    def _is_duplicate(self, plan: OrderPlan, orders: list[ActiveOrder]) -> bool:
        pair = currency_pair(self.pair)
        source = plan.intent.metadata.get("source")
        line_strategy = plan.intent.metadata.get("line_strategy")
        return Portfolio(pair, tuple(orders)).has_similar_active_order(
            plan.intent.direction.value,
            plan.target_price,
            source=source,
            line_strategy=line_strategy,
        )

    def _first_empty_slot(self, priority: int) -> int | None:
        slot_range = self._slot_range(self._priority_tier(priority))
        return next((index for index in slot_range if self.slots[index] is None or not self.slots[index].snapshot.life), None)

    def _first_empty_global_slot(self) -> int | None:
        return next(
            (index for index, slot in enumerate(self.slots) if slot is None or not slot.snapshot.life),
            None,
        )

    def _priority_tier(self, priority: int) -> str:
        if priority >= self.settings.high_priority_threshold:
            return "high"
        if priority >= self.settings.mid_priority_threshold:
            return "mid"
        return "normal"

    def _slot_range(self, tier: str) -> range:
        if tier == "high":
            return range(self.settings.normal_slot_count + self.settings.mid_slot_count, self.settings.max_positions)
        if tier == "mid":
            return range(self.settings.normal_slot_count, self.settings.normal_slot_count + self.settings.mid_slot_count)
        return range(self.settings.normal_slot_count)

    def _available_slot_count(self, tier: str) -> int:
        return sum(
            self.slots[index] is None or not self.slots[index].snapshot.life
            for index in self._slot_range(tier)
        )

    def _apply_linkage(
        self,
        working_slots: list[ManagedPosition | None],
        lifecycle_events: tuple[PositionEvent, ...],
        dry_run: bool,
    ) -> tuple[tuple[PositionCommand, ...], tuple[PositionEvent, ...]]:
        commands: list[PositionCommand] = []
        events: list[PositionEvent] = []
        for event in lifecycle_events:
            main = event.data.get("position")
            if not isinstance(main, ManagedPosition) or main.runtime.linkage_id is None:
                continue
            linked = self._linked_positions(working_slots, main)
            if event.kind == "trade_opened":
                decisions = self.linkage_policy.on_main_filled(linked)
            elif event.kind == "trade_closed":
                broker_snapshot = event.data.get("broker_snapshot")
                if not isinstance(broker_snapshot, PositionSnapshot):
                    continue
                close_price = float(
                    broker_snapshot.average_close_price
                    or broker_snapshot.current_price
                    or main.runtime.target_price
                )
                price_diff = (close_price - main.runtime.target_price) * main.runtime.direction
                decisions = self.linkage_policy.on_main_closed(
                    main_direction=main.runtime.direction,
                    main_price_diff=price_diff,
                    linked_positions=linked,
                )
            else:
                continue
            for decision in decisions:
                command, command_event = self._execute_linkage_decision(
                    working_slots,
                    decision.action,
                    decision.position_id,
                    decision.stop_loss_price,
                    event.kind,
                    dry_run,
                )
                if command is not None:
                    commands.append(command)
                if command_event is not None:
                    events.append(command_event)
        return tuple(commands), tuple(events)

    @staticmethod
    def _linked_positions(
        working_slots: list[ManagedPosition | None],
        main: ManagedPosition,
    ) -> list[LinkedPosition]:
        linked = []
        for position in working_slots:
            if (
                position is None
                or position.snapshot.name == main.snapshot.name
                or position.runtime.linkage_id != main.runtime.linkage_id
            ):
                continue
            plan = position.runtime.order_plan
            stop_loss_range = plan.stop_loss_range if plan is not None else 0.0
            linked.append(
                LinkedPosition(
                    position.snapshot.name,
                    position.runtime.direction,
                    position.runtime.target_price,
                    stop_loss_range,
                    float(position.runtime.current_stop_loss or 0),
                    position.snapshot.order_state,
                    position.snapshot.trade_state,
                    position.snapshot.life,
                    position.runtime.linkage_done,
                )
            )
        return linked

    def _execute_linkage_decision(
        self,
        working_slots: list[ManagedPosition | None],
        action: str,
        position_name: str,
        stop_loss_price: float | None,
        trigger: str,
        dry_run: bool,
    ) -> tuple[PositionCommand | None, PositionEvent | None]:
        match = next(
            (
                (index, position)
                for index, position in enumerate(working_slots)
                if position is not None and position.snapshot.name == position_name
            ),
            None,
        )
        if match is None:
            return None, None
        index, position = match
        if action == "cancel_order":
            reference_id = position.snapshot.order_id
        else:
            reference_id = position.snapshot.trade_id
        command = PositionCommand(action, reference_id, f"linkage_{trigger}", stop_loss_price)
        if dry_run or reference_id is None:
            return command, None
        if action == "cancel_order":
            result = self.broker_execution.cancel_order(reference_id)
            if not result.accepted:
                return command, None
            updated = position.cancelled()
            working_slots[index] = updated
            event = PositionEvent(
                f"order_cancelled:{reference_id}",
                "order_cancelled",
                updated.snapshot.name,
                updated.snapshot.pair,
                self.position_service.clock.now(),
                {"position": updated, "broker_snapshot": updated.snapshot},
            )
            return command, event
        if action == "amend_stop_loss" and stop_loss_price is not None:
            result = self.broker_execution.amend_protection(reference_id, None, stop_loss_price)
            if result.accepted:
                working_slots[index] = position.with_runtime(
                    current_stop_loss=stop_loss_price,
                    linkage_done=True,
                )
            return command, None
        return None, None

    def _apply_hedge(
        self,
        working_slots: list[ManagedPosition | None],
        dry_run: bool,
    ) -> tuple[PositionCommand, ...]:
        open_positions = [
            HedgePosition(
                position.snapshot.name,
                position.runtime.direction,
                position.runtime.unrealized_pl,
            )
            for position in working_slots
            if position is not None and position.snapshot.trade_state.value == "OPEN"
        ]
        commands = []
        for decision in self.hedge_policy.close_commands(open_positions):
            match = next(
                (
                    (index, position)
                    for index, position in enumerate(working_slots)
                    if position is not None and position.snapshot.name == decision.position_id
                ),
                None,
            )
            if match is None:
                continue
            index, position = match
            trade_id = position.snapshot.trade_id
            command = PositionCommand("close_trade", trade_id, "hedge_profit")
            commands.append(command)
            if dry_run or trade_id is None:
                continue
            result = self.broker_execution.close_trade(trade_id)
            if result.accepted:
                working_slots[index] = position.with_runtime(close_requested=True)
        return tuple(commands)
