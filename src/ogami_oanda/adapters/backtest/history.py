"""Bounded legacy reporting bridge for a fresh simulation, without file I/O."""


class SimulationHistory:
    def __init__(self) -> None:
        self.seen: set[str] = set()

    def read_all(self) -> list:
        return []

    def append(self, record) -> None:
        self.append_once(record)

    def append_once(self, record, unique_field="tradeID") -> bool:
        key = str(record[unique_field])
        if key in self.seen:
            return False
        self.seen.add(key)
        return True


class SimulationNotifier:
    def send(self, message, *, category="", pair=None) -> None:
        pass
