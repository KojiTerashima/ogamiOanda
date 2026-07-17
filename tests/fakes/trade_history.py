from __future__ import annotations

from typing import Mapping


class InMemoryTradeHistoryRepository:
    def __init__(self) -> None:
        self.records: list[dict[str, object]] = []

    def append(self, record: Mapping[str, object]) -> None:
        self.records.append(dict(record))
