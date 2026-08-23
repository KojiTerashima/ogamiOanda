from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime

from ogami_oanda.domain.orders.models import OrderPlan

from .models import OrderState, PositionRuntimeState, PositionSnapshot, TradeState


@dataclass(frozen=True)
class ManagedPosition:
    snapshot: PositionSnapshot
    runtime: PositionRuntimeState = field(default_factory=PositionRuntimeState)

    @classmethod
    def registered(cls, name: str, pair: str) -> "ManagedPosition":
        return cls(PositionSnapshot(name=name, pair=pair, order_state=OrderState.REGISTERED, trade_state=TradeState.NONE))

    @classmethod
    def restored(cls, snapshot: PositionSnapshot) -> "ManagedPosition":
        return cls(
            snapshot,
            PositionRuntimeState(
                direction=int(snapshot.direction or 0),
                target_price=float(snapshot.target_price or 0),
                source=snapshot.source,
                line_strategy=snapshot.line_strategy,
                current_stop_loss=snapshot.current_stop_loss,
                restored=True,
            ),
        )

    def with_order_plan(self, order_plan: OrderPlan, registered_at: datetime) -> "ManagedPosition":
        intent = order_plan.intent
        return replace(
            self,
            runtime=replace(
                self.runtime,
                order_plan=order_plan,
                direction=int(intent.direction.value),
                target_price=float(order_plan.target_price),
                source=intent.metadata.get("source"),
                line_strategy=intent.metadata.get("line_strategy"),
                registered_at=registered_at,
                current_stop_loss=float(order_plan.stop_loss_price),
                linkage_id=intent.metadata.get("linkage_id"),
            ),
        )

    def with_runtime(self, **changes: object) -> "ManagedPosition":
        return replace(self, runtime=replace(self.runtime, **changes))

    def watching(self) -> "ManagedPosition":
        return self._replace(order_state=OrderState.WATCHING, waiting_order=True, life=True)

    def pending(self, order_id: str) -> "ManagedPosition":
        return self._replace(order_state=OrderState.PENDING, order_id=order_id, waiting_order=False, life=True)

    def filled(
        self,
        trade_id: str,
        filled_at: datetime | None = None,
        *,
        order_id: str | None = None,
        fill_price: float | None = None,
    ) -> "ManagedPosition":
        changes: dict[str, object] = {
            "order_state": OrderState.FILLED,
            "trade_state": TradeState.OPEN,
            "trade_id": trade_id,
            "waiting_order": False,
            "life": True,
        }
        if order_id is not None:
            changes["order_id"] = order_id
        if fill_price is not None:
            changes["current_price"] = fill_price
        position = self._replace(**changes)
        if filled_at is None or position.runtime.filled_at is not None:
            return position
        return replace(position, runtime=replace(position.runtime, filled_at=filled_at))

    def rejected(self, reason: str = "") -> "ManagedPosition":
        position = self._replace(
            order_state=OrderState.REJECTED,
            waiting_order=False,
            life=False,
        )
        return replace(position, runtime=replace(position.runtime, submission_reason=reason))

    def submission_uncertain(self, reason: str) -> "ManagedPosition":
        position = self._replace(
            order_state=OrderState.SUBMISSION_UNCERTAIN,
            waiting_order=False,
            life=True,
        )
        return replace(position, runtime=replace(position.runtime, submission_reason=reason))

    def cancelled(self) -> "ManagedPosition":
        return self._replace(order_state=OrderState.CANCELLED, waiting_order=False, life=False)

    def closed(self) -> "ManagedPosition":
        return self._replace(trade_state=TradeState.CLOSED, waiting_order=False, life=False)

    def _replace(self, **changes: object) -> "ManagedPosition":
        return replace(self, snapshot=replace(self.snapshot, **changes))
