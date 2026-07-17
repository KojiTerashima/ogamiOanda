from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class StopLossPolicy:
    trigger_range: float
    ensure_range: float

    def amended_stop_loss(self, entry_price: float, direction: int, current_price: float, current_stop_loss: float) -> float | None:
        gain = (current_price - entry_price) * direction
        epsilon = 1e-12
        if gain + epsilon < self.trigger_range:
            return None
        candidate = entry_price + self.ensure_range * direction
        if (candidate - current_stop_loss) * direction <= epsilon:
            return None
        return candidate
