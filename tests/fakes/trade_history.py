from __future__ import annotations

from typing import Mapping


class InMemoryTradeHistoryRepository:
    def __init__(self) -> None:
        self.records: list[dict[str, object]] = []

    def append(self, record: Mapping[str, object]) -> None:
        self.records.append(dict(record))

    def append_once(
        self,
        record: Mapping[str, object],
        *,
        unique_field: str,
    ) -> bool:
        expected = str(record.get(unique_field, ""))
        if expected and any(
            str(item.get(unique_field, "")) == expected
            for item in self.records
        ):
            return False
        self.append(record)
        return True

    def read_all(self) -> tuple[dict[str, object], ...]:
        return tuple(dict(record) for record in self.records)
