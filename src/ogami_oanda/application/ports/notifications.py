from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class Notifier(Protocol):
    def send(self, message: str, *, category: str = "live", pair: str | None = None) -> None: ...
