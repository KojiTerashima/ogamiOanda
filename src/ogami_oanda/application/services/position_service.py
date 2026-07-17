from __future__ import annotations

from ogami_oanda.application.ports.broker import BrokerExecutionPort, BrokerQueryPort
from ogami_oanda.application.ports.clock import Clock
from ogami_oanda.application.ports.notifications import Notifier
from ogami_oanda.application.ports.trade_history import TradeHistoryRepository
from ogami_oanda.domain.orders.models import OrderPlan
from ogami_oanda.domain.positions.managed_position import ManagedPosition


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

    def register(self, position: ManagedPosition, order_plan: OrderPlan, submit: bool = True) -> ManagedPosition:
        if not submit:
            return position.watching()
        result = self.broker_execution.submit(order_plan.broker_request)
        if not result.accepted or result.reference_id is None:
            self.notifier.send(f"Order rejected: {position.snapshot.name}", pair=position.snapshot.pair)
            return position.cancelled()
        self.notifier.send(f"Order submitted: {position.snapshot.name}", pair=position.snapshot.pair)
        return position.pending(result.reference_id)

    def sync(self, position: ManagedPosition) -> ManagedPosition:
        if position.snapshot.trade_id is not None:
            broker_snapshot = self.broker_query.trade(position.snapshot.trade_id)
        elif position.snapshot.order_id is not None:
            broker_snapshot = self.broker_query.order(position.snapshot.order_id)
        else:
            return position
        if broker_snapshot is None:
            return position
        if broker_snapshot.order_state.value in {"CANCELLED", "REJECTED"}:
            return position.cancelled()
        if broker_snapshot.trade_state.value == "CLOSED":
            return position.closed()
        if broker_snapshot.trade_id and broker_snapshot.trade_state.value == "OPEN":
            return position.filled(broker_snapshot.trade_id)
        return position

    def close(self, position: ManagedPosition) -> ManagedPosition:
        trade_id = position.snapshot.trade_id
        if trade_id is None:
            return position.cancelled()
        result = self.broker_execution.close_trade(trade_id)
        if not result.accepted:
            return position
        closed = position.closed()
        self.history.append({"name": closed.snapshot.name, "pair": closed.snapshot.pair, "closed_at": self.clock.now().isoformat()})
        self.notifier.send(f"Trade closed: {closed.snapshot.name}", pair=closed.snapshot.pair)
        return closed
