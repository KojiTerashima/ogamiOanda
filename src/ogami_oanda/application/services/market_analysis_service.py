from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Mapping

import pandas as pd

from ogami_oanda.application.ports.market_data import MarketDataPort
from ogami_oanda.application.services.portfolio import Portfolio
from ogami_oanda.domain.analysis.indicators import add_basic_data, add_bb_data, add_rsi
from ogami_oanda.domain.analysis.peaks import PeaksClass
from ogami_oanda.domain.market.candle_frame import CandleFrameSchema
from ogami_oanda.domain.market.currency_pair import currency_pair
from ogami_oanda.domain.orders.models import Direction, OrderIntent, OrderType

CandidateBuilder = Callable[[Mapping[str, object], float], list[dict]]


@dataclass(frozen=True)
class MarketAnalysisResult:
    intents: tuple[OrderIntent, ...]
    frames: Mapping[str, pd.DataFrame]
    peaks: Mapping[str, PeaksClass]


class MarketAnalysisService:
    def __init__(
        self,
        market_data: MarketDataPort,
        candidate_builder: CandidateBuilder,
        active_orders: Portfolio | None = None,
        units: int = 1000,
        candle_count: int = 250,
    ) -> None:
        self.market_data = market_data
        self.candidate_builder = candidate_builder
        self.active_orders = active_orders
        self.units = units
        self.candle_count = candle_count

    def analyze(self, pair: str, decision_time: str) -> MarketAnalysisResult:
        current_price = self.market_data.current_price(pair)
        frames = {granularity: self._prepared_frame(pair, granularity) for granularity in ("M5", "H1", "M30", "S5")}
        peaks = {
            granularity: PeaksClass(frame, granularity, current_price, currency_pair(pair))
            for granularity, frame in frames.items()
            if granularity != "S5"
        }
        candidates = self.candidate_builder({"frames": frames, "peaks": peaks, "decision_time": decision_time}, current_price)
        intents = tuple(intent for candidate in candidates if (intent := self._candidate_to_intent(pair, candidate, current_price)) is not None)
        return MarketAnalysisResult(intents, frames, peaks)

    def _prepared_frame(self, pair: str, granularity: str) -> pd.DataFrame:
        frame = self.market_data.candles(pair, granularity, self.candle_count).copy()
        if {"mid", "complete"}.issubset(frame.columns):
            frame = add_basic_data(frame, currency_pair(pair))
        elif "body" not in frame.columns:
            frame["body"] = frame["close"] - frame["open"]
        if "moves" not in frame.columns:
            frame["moves"] = frame["high"] - frame["low"]
        if "body_abs" not in frame.columns:
            frame["body_abs"] = frame["body"].abs()
        if "middle_price" not in frame.columns:
            frame["middle_price"] = (frame["inner_low"] + frame["inner_high"]) / 2
        if "RSI" not in frame.columns:
            frame = add_rsi(frame)
        if granularity != "S5" and "bb_range" not in frame.columns:
            frame = add_bb_data(frame, currency_pair(pair))
        CandleFrameSchema(pair, granularity).validate(frame)
        return frame

    def _candidate_to_intent(self, pair: str, candidate: dict, current_price: float) -> OrderIntent | None:
        direction = Direction.BUY if int(candidate["direction"]) == 1 else Direction.SELL
        strategy = candidate.get("strategy")
        order_type = OrderType(candidate.get("order_type_override", getattr(strategy, "order_type", "LIMIT")))
        target_price = float(candidate["target_price"])
        source = candidate.get("source", "line")
        line_strategy = candidate.get("line_strategy")
        if self.active_orders and self.active_orders.has_similar_active_order(direction.value, target_price, source=source, line_strategy=line_strategy):
            return None
        pair_info = currency_pair(pair)
        lc_pips = float(candidate.get("lc_pips", getattr(strategy, "lc_pips", 0)))
        tp_pips = float(candidate.get("tp_pips", getattr(strategy, "get_tp_pips", lambda: 0)()))
        return OrderIntent(
            pair=pair,
            direction=direction,
            order_type=order_type,
            target=target_price if order_type is not OrderType.MARKET else 0,
            target_is_price=order_type is not OrderType.MARKET,
            take_profit=pair_info.pips_to_price(tp_pips),
            take_profit_is_price=False,
            stop_loss=pair_info.pips_to_price(lc_pips),
            stop_loss_is_price=False,
            units=int(candidate.get("units", self.units)),
            name=str(candidate.get("name", f"{line_strategy}_{candidate.get('line_side', 'entry')}")),
            priority=int(candidate.get("priority", candidate.get("line", {}).get("total_strength", 0))),
            order_timeout_min=int(candidate.get("order_timeout_min", getattr(strategy, "order_timeout_min", 0))),
            metadata={key: value for key, value in candidate.items() if key not in {"strategy", "line"}},
        )
