from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, runtime_checkable

import pandas as pd


@dataclass(frozen=True)
class MarketQuote:
    """One pricing tick shared by analysis and position management."""

    pair: str
    bid: float
    ask: float
    mid: float
    tradeable: bool = True
    source_time: datetime | None = None

    @property
    def spread(self) -> float:
        return self.ask - self.bid


@runtime_checkable
class MarketDataPort(Protocol):
    def candles(self, pair: str, granularity: str, count: int) -> pd.DataFrame: ...

    def current_price(self, pair: str) -> float: ...

    def current_quote(self, pair: str) -> MarketQuote: ...
