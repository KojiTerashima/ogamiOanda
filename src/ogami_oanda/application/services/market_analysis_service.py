from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Mapping

import pandas as pd

from ogami_oanda.application.ports.active_orders import ActiveOrderQuery
from ogami_oanda.application.ports.market_data import MarketDataPort
from ogami_oanda.domain.analysis.indicators import add_basic_data, add_bb_data, add_rsi
from ogami_oanda.domain.analysis.peaks import PeaksClass
from ogami_oanda.domain.market.candle_frame import CandleFrameSchema
from ogami_oanda.domain.market.currency_pair import currency_pair
from ogami_oanda.domain.orders.models import (
    Direction,
    OrderContext,
    OrderIntent,
    OrderType,
)

CandidateBuilder = Callable[[Mapping[str, object], float], list[dict]]
CandidateContextBuilder = Callable[[str, Mapping[str, pd.DataFrame], Mapping[str, PeaksClass], float, str], Mapping[str, object]]


@dataclass(frozen=True)
class MarketAnalysisResult:
    intents: tuple[OrderIntent, ...]
    frames: Mapping[str, pd.DataFrame]
    peaks: Mapping[str, PeaksClass]
    order_context: OrderContext | None = None
    candidate_context: Mapping[str, object] = field(default_factory=dict)


class MarketAnalysisService:
    def __init__(
        self,
        market_data: MarketDataPort,
        candidate_builder: CandidateBuilder,
        active_orders: ActiveOrderQuery | None = None,
        candidate_context_builder: CandidateContextBuilder | None = None,
        units: int = 1000,
        candle_count: int = 250,
    ) -> None:
        self.market_data = market_data
        self.candidate_builder = candidate_builder
        self.candidate_context_builder = candidate_context_builder
        self.active_orders = active_orders
        self.units = units
        self.candle_count = candle_count

    def analyze(
        self,
        pair: str,
        decision_time: str,
        *,
        current_price: float | None = None,
    ) -> MarketAnalysisResult:
        current_price = self.market_data.current_price(pair) if current_price is None else current_price
        frames = {granularity: self._prepared_frame(pair, granularity) for granularity in ("M5", "H1", "M30", "S5")}
        peaks = {
            granularity: PeaksClass(frame, granularity, current_price, currency_pair(pair))
            for granularity, frame in frames.items()
            if granularity != "S5"
        }
        context = (
            self.candidate_context_builder(pair, frames, peaks, current_price, decision_time)
            if self.candidate_context_builder is not None
            else {"frames": frames, "peaks": peaks, "decision_time": decision_time}
        )
        candidates = self.candidate_builder(context, current_price)
        order_context = OrderContext(
            current_price,
            str(context.get("order_decision_time", frames["M5"].iloc[0]["time_jp"])),
            float(context.get("move_ave", 0)),
        )
        intents = tuple(
            intent
            for candidate in candidates
            if (intent := self._candidate_to_intent(pair, candidate, current_price, context, order_context)) is not None
        )
        return MarketAnalysisResult(intents, frames, peaks, order_context, context)

    def _prepared_frame(self, pair: str, granularity: str) -> pd.DataFrame:
        frame = self.market_data.candles(pair, granularity, self.candle_count).copy()
        if "body" not in frame.columns:
            frame = add_basic_data(frame, currency_pair(pair))
        needs_rsi = "RSI" not in frame.columns
        needs_bb = granularity != "S5" and "bb_range" not in frame.columns
        if needs_rsi or needs_bb:
            frame = frame.sort_values("time_jp", ascending=True).reset_index(drop=True)
            if needs_rsi:
                frame = add_rsi(frame)
            if needs_bb:
                frame = add_bb_data(frame, currency_pair(pair))
            frame = frame.sort_values("time_jp", ascending=False).reset_index(drop=True)
        CandleFrameSchema(pair, granularity).validate(frame)
        return frame

    def _candidate_to_intent(
        self,
        pair: str,
        candidate: dict,
        current_price: float,
        context: Mapping[str, object],
        order_context: OrderContext,
    ) -> OrderIntent | None:
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
        units_multiplier = float(candidate.get("units_multiplier", 1))
        units = int(candidate.get("units", self.units * units_multiplier))
        base_name = str(candidate.get("name", f"{line_strategy}_{candidate.get('line_side', 'entry')}"))
        name = self._legacy_order_name(base_name, order_context.decision_time) if candidate.get("source") == "line" else base_name
        position_management: dict[str, object] = {}
        if candidate.get("trade_timeout_min") is not None:
            position_management["trade_timeout_min"] = int(candidate["trade_timeout_min"])
        if candidate.get("lc_change") is not None:
            raw_rules = candidate["lc_change"]
            rules = (raw_rules,) if isinstance(raw_rules, Mapping) else raw_rules
            position_management["lc_change"] = tuple(dict(rule) for rule in rules)
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
            units=units,
            name=name,
            priority=int(candidate.get("priority", candidate.get("line", {}).get("total_strength", 0))),
            order_timeout_min=int(candidate.get("order_timeout_min", getattr(strategy, "order_timeout_min", 0))),
            metadata=self._intent_metadata(candidate, context, current_price, order_context, base_name),
            **position_management,
        )

    @staticmethod
    def _legacy_order_name(base_name: str, decision_time: str) -> str:
        return f"{base_name}_{pd.to_datetime(decision_time).strftime('%H:%M')}"

    def _intent_metadata(
        self,
        candidate: Mapping[str, object],
        context: Mapping[str, object],
        current_price: float,
        order_context: OrderContext,
        base_name: str,
    ) -> dict[str, object]:
        metadata = {key: value for key, value in candidate.items() if key not in {"strategy", "line", "h1_context"}}
        line = candidate.get("line") or {}
        pair = currency_pair(self._pair_name(candidate))
        target_price = float(candidate["target_price"])
        legacy_metadata = {
            "source": candidate.get("source", "line"),
            "line_timeframe": candidate.get("line_timeframe", candidate.get("timeframe")),
            "line_side": candidate.get("line_side"),
            "line_price": candidate.get("line_price"),
            "line_total_strength": line.get("total_strength"),
            "line_count": line.get("count"),
            "line_ave_strength": line.get("ave_strength"),
            "line_is_flipped": line.get("is_flipped_line"),
            "line_oldest_time": line.get("oldest_time"),
            "core_median_price": line.get("core_median_price"),
            "core_count": line.get("core_count"),
            "core_total_strength": line.get("core_total_strength"),
            "line_strategy": candidate.get("line_strategy"),
            "line_entry_type": candidate.get("line_entry_type"),
            "line_entry_offset_pips": candidate.get("line_entry_offset_pips"),
            "line_order_mode": "immediate" if candidate.get("order_mode") == "immediate" else "limit",
            "line_target_price": candidate.get("line_target_price", target_price),
            "line_distance_pips": candidate.get("distance_pips"),
            "target_distance_pips": abs(pair.price_to_pips(target_price - current_price)),
            "decision_price": current_price,
            "session_lc_multiplier": candidate.get("session_lc_multiplier", 1.0),
            "session_tp_multiplier": candidate.get("session_tp_multiplier", 1.0),
            "session_units_multiplier": candidate.get("session_units_multiplier", 1.0),
            "session_rr": candidate.get("session_rr"),
            "session_skip_reason": candidate.get("session_skip_reason"),
        }
        legacy_metadata.update({
            key: candidate.get(key)
            for key in (
                "latest_peak_dir",
                "latest_peak_count",
                "latest_peak_gap",
                "latest_peak_time",
                "latest_peak_strength",
                "latest_peak_price",
                "latest_peak_rsi",
                "previous_peak_dir",
                "previous_peak_count",
                "previous_peak_gap",
                "previous_peak_time",
                "previous_peak_strength",
                "previous_peak_price",
                "previous_peak_rsi",
            )
        })
        session_time = pd.to_datetime(order_context.decision_time)
        session_hour = int(session_time.hour)
        legacy_metadata.update({
            "session_name": "morning" if 6 <= session_hour < 12 else "day" if 12 <= session_hour < 18 else "night",
            "session_hour": session_hour,
            "session_time": session_time.strftime("%Y/%m/%d %H:%M:%S"),
        })
        legacy_metadata.update({
            key: line.get(key)
            for key in ("line_peak_rsi_avg", "line_peak_rsi_count", "line_peak_rsi_latest")
        })
        legacy_metadata.update({key: value for key, value in line.items() if key.startswith("line_")})
        legacy_metadata.update(candidate.get("h1_context") or {})
        legacy_metadata.update(context.get("rsi_info") or {})
        metadata["name_ymdhms"] = f"{base_name}_{order_context.decision_time}"
        metadata["candle_lc_change_type"] = "5M"
        metadata["legacy_plan_metadata"] = legacy_metadata
        return metadata

    @staticmethod
    def _pair_name(candidate: Mapping[str, object]) -> str:
        strategy = candidate.get("strategy")
        return str(getattr(strategy, "pair", "USD_JPY"))
