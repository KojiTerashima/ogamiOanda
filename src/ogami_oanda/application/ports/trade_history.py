from __future__ import annotations

from typing import Mapping, Protocol, runtime_checkable


@runtime_checkable
class TradeHistoryRepository(Protocol):
    def append(self, record: Mapping[str, object]) -> None: ...

    def append_once(
        self,
        record: Mapping[str, object],
        *,
        unique_field: str,
    ) -> bool: ...

    def read_all(self) -> tuple[Mapping[str, object], ...]: ...
