from __future__ import annotations

from dataclasses import dataclass, replace

from .models import OrderState, PositionSnapshot, TradeState


@dataclass(frozen=True)
class ManagedPosition:
    snapshot: PositionSnapshot

    @classmethod
    def registered(cls, name: str, pair: str) -> "ManagedPosition":
        return cls(PositionSnapshot(name=name, pair=pair, order_state=OrderState.REGISTERED, trade_state=TradeState.NONE))

    def watching(self) -> "ManagedPosition":
        return self._replace(order_state=OrderState.WATCHING, waiting_order=True, life=True)

    def pending(self, order_id: str) -> "ManagedPosition":
        return self._replace(order_state=OrderState.PENDING, order_id=order_id, waiting_order=False, life=True)

    def filled(self, trade_id: str) -> "ManagedPosition":
        return self._replace(order_state=OrderState.FILLED, trade_state=TradeState.OPEN, trade_id=trade_id, waiting_order=False, life=True)

    def cancelled(self) -> "ManagedPosition":
        return self._replace(order_state=OrderState.CANCELLED, waiting_order=False, life=False)

    def closed(self) -> "ManagedPosition":
        return self._replace(trade_state=TradeState.CLOSED, waiting_order=False, life=False)

    def _replace(self, **changes: object) -> "ManagedPosition":
        return ManagedPosition(replace(self.snapshot, **changes))
