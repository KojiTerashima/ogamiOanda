from __future__ import annotations

from collections import deque

from ogami_oanda.domain.positions.models import PositionEvent


class RuntimeEventBuffer:
    """Small in-process bridge from domain services to a live observer.

    The buffer is intentionally transient: event IDs are persisted by the
    position service, while this queue only carries events produced since the
    previous completed polling tick.
    """

    def __init__(self) -> None:
        self._events: deque[PositionEvent] = deque()

    def publish(self, event: PositionEvent) -> None:
        self._events.append(event)

    def drain(self) -> tuple[PositionEvent, ...]:
        events = tuple(self._events)
        self._events.clear()
        return events
