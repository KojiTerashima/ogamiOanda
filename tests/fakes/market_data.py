from __future__ import annotations

import pandas as pd

from ogami_oanda.application.ports.market_data import MarketQuote


class FakeMarketData:
    def __init__(self, frames: dict[tuple[str, str], pd.DataFrame], prices: dict[str, float]) -> None:
        self.frames = frames
        self.prices = prices

    def candles(self, pair: str, granularity: str, count: int) -> pd.DataFrame:
        return self.frames[(pair, granularity)].head(count).copy()

    def current_price(self, pair: str) -> float:
        return self.prices[pair]

    def current_quote(self, pair: str) -> MarketQuote:
        mid = self.current_price(pair)
        return MarketQuote(pair, mid, mid, mid)
