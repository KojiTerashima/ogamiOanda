"""Market-data orchestration and compatibility facade for original analysis."""

from __future__ import annotations

from ogami_oanda.application.ports.active_orders import ActiveOrderQuery
from ogami_oanda.application.ports.market_data import MarketDataPort
from ogami_oanda.strategy.original.analysis import (
    CandidateBuilder as CandidateBuilder,
    CandidateContextBuilder as CandidateContextBuilder,
    MarketAnalysisResult as MarketAnalysisResult,
    OriginalAnalysis,
)
from ogami_oanda.strategy.original.strategy import OriginalStrategy
from ogami_oanda.strategy.shared.contracts import StrategyInput, StrategyQuote


class MarketAnalysisService(OriginalAnalysis):
    def __init__(
        self,
        market_data: MarketDataPort,
        candidate_builder: CandidateBuilder | None = None,
        active_orders: ActiveOrderQuery | None = None,
        candidate_context_builder: CandidateContextBuilder | None = None,
        units: int = 1000,
        candle_count: int = 250,
        *,
        strategy: OriginalStrategy | None = None,
    ) -> None:
        if strategy is None and candidate_builder is None:
            raise ValueError("candidate_builder or strategy is required")
        super().__init__(candidate_builder, active_orders, candidate_context_builder, units)
        self.market_data = market_data
        self.candle_count = candle_count
        self.strategy = strategy
        self._injected_strategy = strategy is not None
        self.last_decision = None

    def analyze(self, pair: str, decision_time: str, *, current_price: float | None = None) -> MarketAnalysisResult:
        current_price = self.market_data.current_price(pair) if current_price is None else current_price
        if self.strategy is None or (not self._injected_strategy and self.strategy.pair != pair):
            self.strategy = OriginalStrategy(pair=pair, _analysis=self)
        frames = {
            granularity: self.market_data.candles(pair, granularity, self.candle_count)
            for granularity in self.strategy.data_requirements
        }
        self.last_decision = self.strategy.decide(StrategyInput(
            quote=StrategyQuote(pair, current_price, current_price, current_price),
            candle_frames=frames,
            decision_time=decision_time,
        ))
        return self.strategy.last_analysis

    def _prepared_frame(self, pair: str, granularity: str):
        return self.prepare_frame(
            pair, granularity,
            self.market_data.candles(pair, granularity, self.candle_count),
        )
