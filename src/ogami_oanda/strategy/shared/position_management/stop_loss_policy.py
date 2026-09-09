from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Iterable, Mapping


@dataclass(frozen=True)
class StopLossAmendment:
    rule_index: int
    stop_loss_price: float


@dataclass(frozen=True)
class StopLossPolicy:
    trigger_range: float = 0.0
    ensure_range: float = 0.0
    price_digits: int = 3

    def amended_stop_loss(self, entry_price: float, direction: int, current_price: float, current_stop_loss: float) -> float | None:
        gain = (current_price - entry_price) * direction
        epsilon = 1e-12
        if gain + epsilon < self.trigger_range:
            return None
        candidate = entry_price + self.ensure_range * direction
        if (candidate - current_stop_loss) * direction <= epsilon:
            return None
        return round(candidate, self.price_digits)

    def next_amendment(
        self,
        rules: Iterable[Mapping[str, object]],
        entry_price: float,
        direction: int,
        current_price: float,
        current_stop_loss: float,
        elapsed_seconds: float,
        applied_indices: set[int] | None = None,
    ) -> StopLossAmendment | None:
        applied = applied_indices or set()
        gain = (current_price - entry_price) * direction
        for index, rule in enumerate(rules):
            if not bool(rule.get("exe")) or index in applied or "done" in rule:
                continue
            if elapsed_seconds < float(rule.get("time_after", 0)):
                continue
            if elapsed_seconds > float(rule.get("time_till", 100000)):
                continue
            trigger = float(rule["trigger"])
            if gain + 1e-12 < trigger:
                continue
            candidate = round(entry_price + float(rule["ensure"]) * direction, self.price_digits)
            if (candidate - current_stop_loss) * direction <= 1e-12:
                continue
            return StopLossAmendment(index, candidate)
        return None

    def candle_amendment(
        self,
        entry_price: float,
        direction: int,
        current_stop_loss: float,
        elapsed_seconds: float,
        latest_peak: Mapping[str, object],
        previous_candle: Mapping[str, object],
        now: datetime,
        *,
        enabled: bool = True,
        already_done: bool = False,
        add_margin: float = 0.015,
        minimum_ensure_range: float = 0.01,
    ) -> float | None:
        if not enabled or already_done or elapsed_seconds < 30:
            return None
        if now.minute % 5 != 0 or not 6 <= now.second < 30:
            return None
        if int(latest_peak.get("count") or 0) < 3 or int(latest_peak.get("direction") or 0) != direction:
            return None
        candidate = (
            float(previous_candle["low"]) - add_margin
            if direction == 1
            else float(previous_candle["high"]) + add_margin
        )
        if abs(entry_price - candidate) <= minimum_ensure_range:
            return None
        if (candidate - entry_price) * direction < 0:
            return None
        candidate = round(candidate, self.price_digits)
        if (candidate - current_stop_loss) * direction <= 1e-12:
            return None
        return candidate
