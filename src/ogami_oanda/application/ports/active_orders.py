from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class ActiveOrderQuery(Protocol):
    def has_similar_active_order(
        self,
        direction: int,
        target_price: float,
        threshold_pips: float = 3,
        source: str | None = None,
        line_strategy: str | None = None,
    ) -> bool: ...
