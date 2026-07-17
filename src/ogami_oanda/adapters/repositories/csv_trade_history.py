from __future__ import annotations

import csv
from pathlib import Path
from typing import Mapping


class CsvTradeHistoryRepository:
    def __init__(self, history_file: str | Path) -> None:
        self.path = Path(history_file)

    def append(self, record: Mapping[str, object]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        exists = self.path.exists()
        with self.path.open("a", newline="", encoding="utf-8") as history:
            writer = csv.DictWriter(history, fieldnames=list(record.keys()))
            if not exists:
                writer.writeheader()
            writer.writerow(record)
