from __future__ import annotations

from typing import Any

import pandas as pd


class LegacyCandleAnalysisMarketData:
    """Expose a legacy candle-analysis instance through MarketDataPort."""

    def __init__(self, candle_analysis: Any) -> None:
        m5_frame = candle_analysis.d5_df_r
        self.pair = str(getattr(candle_analysis, "pair", "USD_JPY"))
        self.frames = {
            "M5": m5_frame,
            "H1": candle_analysis.h1_df_r,
            "M30": candle_analysis.d30_df_r,
            "S5": candle_analysis.s5_df_r if candle_analysis.s5_df_r is not None else m5_frame,
        }
        self.price = float(candle_analysis.current_price)

    def candles(self, pair: str, granularity: str, count: int) -> pd.DataFrame:
        if pair != self.pair:
            raise ValueError(f"Legacy candle pair mismatch: {pair} != {self.pair}")
        return self.frames[granularity].head(count).copy()

    def current_price(self, pair: str) -> float:
        if pair != self.pair:
            raise ValueError(f"Legacy candle pair mismatch: {pair} != {self.pair}")
        return self.price