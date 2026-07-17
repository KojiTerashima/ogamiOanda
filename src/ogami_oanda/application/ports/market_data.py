from __future__ import annotations

from typing import Protocol, runtime_checkable

import pandas as pd


@runtime_checkable
class MarketDataPort(Protocol):
    def candles(self, pair: str, granularity: str, count: int) -> pd.DataFrame: ...

    def current_price(self, pair: str) -> float: ...
