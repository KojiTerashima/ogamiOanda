from __future__ import annotations


class FakeNotifier:
    def __init__(self) -> None:
        self.messages: list[tuple[str, str, str | None]] = []

    def send(self, message: str, *, category: str = "live", pair: str | None = None) -> None:
        self.messages.append((message, category, pair))
