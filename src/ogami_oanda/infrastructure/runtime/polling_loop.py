from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable, Generic, Protocol, TypeVar


class Sleeper(Protocol):
    def __call__(self, seconds: float) -> None: ...


ResultT = TypeVar("ResultT")


@dataclass(frozen=True)
class PollingLoop(Generic[ResultT]):
    """Infrastructure-owned fixed-interval loop around a single use-case tick."""

    interval_seconds: float = 1.0
    sleeper: Sleeper = time.sleep
    monotonic: Callable[[], float] = time.monotonic

    def run(
        self,
        tick: Callable[[], ResultT],
        *,
        max_ticks: int | None = None,
    ) -> tuple[ResultT, ...]:
        if self.interval_seconds <= 0:
            raise ValueError("interval_seconds must be positive")
        if max_ticks is not None and max_ticks < 0:
            raise ValueError("max_ticks must be non-negative")

        collect_results = max_ticks is not None
        results: list[ResultT] = []
        tick_count = 0
        next_deadline = self.monotonic()
        while max_ticks is None or tick_count < max_ticks:
            result = tick()
            if collect_results:
                results.append(result)
            tick_count += 1
            if max_ticks is None or tick_count < max_ticks:
                next_deadline += self.interval_seconds
                now = self.monotonic()
                if next_deadline <= now:
                    missed_intervals = int((now - next_deadline) // self.interval_seconds) + 1
                    next_deadline += missed_intervals * self.interval_seconds
                self.sleeper(next_deadline - now)
        return tuple(results)
