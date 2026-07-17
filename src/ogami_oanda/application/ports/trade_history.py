from __future__ import annotations

from typing import Mapping, Protocol, runtime_checkable


@runtime_checkable
class TradeHistoryRepository(Protocol):
    def append(self, record: Mapping[str, object]) -> None: ...
