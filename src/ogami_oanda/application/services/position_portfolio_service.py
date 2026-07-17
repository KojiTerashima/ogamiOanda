from __future__ import annotations

from dataclasses import dataclass

from ogami_oanda.application.ports.broker import BrokerExecutionPort, BrokerQueryPort
from ogami_oanda.application.services.portfolio import ActiveOrder, Portfolio
from ogami_oanda.application.services.position_service import PositionService
from ogami_oanda.domain.market.currency_pair import currency_pair
from ogami_oanda.domain.orders.models import OrderPlan
from ogami_oanda.domain.positions.managed_position import ManagedPosition
from ogami_oanda.infrastructure.config.models import TradingSettings


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


class PositionPortfolioService:
    def __init__(self, pair: str, position_service: PositionService, broker_query: BrokerQueryPort, broker_execution: BrokerExecutionPort, settings: TradingSettings = TradingSettings()) -> None:
        self.pair = pair
        self.position_service = position_service
        self.broker_query = broker_query
        self.broker_execution = broker_execution
        self.settings = settings
        self.slots: list[ManagedPosition | None] = [None] * settings.max_positions

    def register_plans(self, plans: list[OrderPlan], submit: bool = True) -> RegistrationResult:
        accepted: list[str] = []
        rejected: list[tuple[str, str]] = []
        batch_orders = self._active_orders()
        for plan in plans:
            intent = plan.intent
            if intent.pair != self.pair:
                rejected.append((intent.name, "pair_mismatch"))
                continue
            if self._is_duplicate(plan, batch_orders):
                rejected.append((intent.name, "duplicate"))
                continue
            slot_index = self._first_empty_slot(intent.priority)
            if slot_index is None:
                rejected.append((intent.name, "tier_full"))
                continue
            position = ManagedPosition.registered(intent.name, self.pair)
            position = self.position_service.register(position, plan, submit=submit)
            if position.snapshot.life:
                self.slots[slot_index] = position
                batch_orders.append(ActiveOrder(intent.name, intent.direction.value, plan.target_price, intent.metadata.get("source"), intent.metadata.get("line_strategy")))
                accepted.append(intent.name)
            else:
                rejected.append((intent.name, "broker_rejected"))
        return RegistrationResult(tuple(accepted), tuple(rejected))

    def sync_all(self) -> PortfolioSummary:
        for index, position in enumerate(self.slots):
            if position is not None and position.snapshot.life:
                self.slots[index] = self.position_service.sync(position)
        return self.summary()

    def restore_open_positions(self) -> tuple[str, ...]:
        restored: list[str] = []
        for snapshot in self.broker_query.open_positions():
            if snapshot.pair != self.pair or not snapshot.life or self._first_empty_slot(self.settings.high_priority_threshold) is None:
                continue
            index = self._first_empty_slot(self.settings.high_priority_threshold)
            if index is None:
                break
            self.slots[index] = ManagedPosition(snapshot)
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
                1 if slot.snapshot.trade_state.value == "OPEN" else 1,
                0.0,
            )
            for slot in self.slots
            if slot is not None and slot.snapshot.life
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
        if priority >= self.settings.high_priority_threshold:
            slot_range = range(self.settings.normal_slot_count + self.settings.mid_slot_count, self.settings.max_positions)
        elif priority >= self.settings.mid_priority_threshold:
            slot_range = range(self.settings.normal_slot_count, self.settings.normal_slot_count + self.settings.mid_slot_count)
        else:
            slot_range = range(self.settings.normal_slot_count)
        return next((index for index in slot_range if self.slots[index] is None or not self.slots[index].snapshot.life), None)
