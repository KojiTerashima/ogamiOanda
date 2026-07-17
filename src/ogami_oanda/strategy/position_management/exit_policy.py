from __future__ import annotations

from dataclasses import dataclass

from ogami_oanda.domain.positions.models import PositionSnapshot, TradeState


@dataclass(frozen=True)
class ExitPolicy:
    trade_timeout_min: int

    def should_close(self, position: PositionSnapshot, elapsed_seconds: float) -> bool:
        return position.trade_state is TradeState.OPEN and elapsed_seconds >= self.trade_timeout_min * 60
