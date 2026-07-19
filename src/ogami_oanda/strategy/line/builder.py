from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from .aud_usd import LineStrategyProfileAudUsd
from .coordinator import LineCandidateCoordinator
from .eur_usd import LineStrategyProfileEurUsd
from .order_timeout import order_timeout_min_for_distance
from .usd_jpy import (
    LineStrategyProfileUsdJpy,
    UsdJpyM5BreakoutLineOrderStrategy,
    UsdJpyM5LineOrderStrategy,
)

_TIMEOUT_BY_DISTANCE_PIPS = ((3, 15), (7, 30), (12, 45))
_TIMEOUT_CAP_BY_TIMEFRAME = {"m5": 45, "h1": 60}


@dataclass(frozen=True)
class _AnalysisView:
    pair: str
    peaks_class: object
    peaks_class_hour: object


def line_strategy_profile_for_pair(pair: str):
    if pair == "AUD_USD":
        return LineStrategyProfileAudUsd()
    if pair == "EUR_USD":
        return LineStrategyProfileEurUsd()
    return LineStrategyProfileUsdJpy()


class LineCandidateBuilder:
    """Build selected line candidate dicts without legacy order creation."""

    def __init__(self, pair: str, profile=None) -> None:
        self.pair = pair
        self.profile = profile or line_strategy_profile_for_pair(pair)

    def __call__(self, context: Mapping[str, object], current_price: float) -> list[dict]:
        raw_candidates = self.build_raw_candidates(context, current_price)
        selected = self.select_candidates(raw_candidates, context)
        return self.enrich_candidates(selected, current_price)

    def build_raw_candidates(self, context: Mapping[str, object], current_price: float) -> dict[str, list[dict]]:
        peaks = context["peaks"]
        analysis = _AnalysisView(
            pair=self.pair,
            peaks_class=peaks["M5"],
            peaks_class_hour=peaks["H1"],
        )
        coordinator = LineCandidateCoordinator(analysis, self.profile)
        h1_line_class = context["line_class_h1_main"]
        m5_line_class = context["line_class_m5_main"]

        raw_candidates: dict[str, list[dict]] = {}
        for mode in ("immediate", "future_resist", "future_break"):
            raw_candidates[mode] = coordinator.build_line_candidates(
                self._strategy_lines_for_mode(mode, m5_line_class),
                current_price,
                h1_line_class=h1_line_class,
                m5_line_class=m5_line_class,
                order_mode="immediate" if mode == "immediate" else "limit",
            )
        return raw_candidates

    def select_candidates(self, raw_candidates: Mapping[str, list[dict]], context: Mapping[str, object]) -> list[dict]:
        peaks = context["peaks"]
        analysis = _AnalysisView(
            pair=self.pair,
            peaks_class=peaks["M5"],
            peaks_class_hour=peaks["H1"],
        )
        coordinator = LineCandidateCoordinator(analysis, self.profile)
        decision_time = context["decision_time"]
        rsi_info = context.get("rsi_info")

        selected = []
        for mode in ("immediate", "future_resist", "future_break"):
            selected.extend(
                coordinator.select_line_candidates(
                    list(raw_candidates.get(mode, [])),
                    rsi_info,
                    decision_time,
                    mode,
                    self._reason_func_for_mode(mode),
                )
            )
        return selected

    def enrich_candidates(self, selected_candidates: list[dict], current_price: float) -> list[dict]:
        enriched = []
        for candidate in selected_candidates:
            strategy = candidate["strategy"]
            order_mode = candidate.get("order_mode", "limit")
            item = dict(candidate)
            item["name"] = (
                strategy.name_prefix
                + ("Immediate" if order_mode == "immediate" else "")
                + "_"
                + candidate["line_side"]
                + "_"
                + str(candidate["line_index"])
            )
            item["lc_pips"] = float(strategy.lc_pips)
            item["tp_pips"] = float(strategy.get_tp_pips())
            item["units_multiplier"] = float(strategy.units_multiplier)
            item["units"] = int(candidate.get("units", 0))
            item["priority"] = int(candidate.get("line", {}).get("total_strength", 0))
            item["source"] = "line"
            item["line_order_mode"] = order_mode
            item["line_timeframe"] = strategy.timeframe
            item["line_entry_type"] = strategy.entry_type
            item["line_entry_offset_pips"] = strategy.entry_offset_pips
            if order_mode == "immediate":
                item["order_timeout_min"] = 0
                item["target_price"] = float(current_price)
                item["order_type_override"] = "MARKET"
            else:
                item["order_timeout_min"] = order_timeout_min_for_distance(
                    candidate.get("distance_pips", 0),
                    str(strategy.timeframe),
                    int(strategy.order_timeout_min),
                    _TIMEOUT_BY_DISTANCE_PIPS,
                    _TIMEOUT_CAP_BY_TIMEFRAME,
                )
            enriched.append(item)
        return enriched

    def _strategy_lines_for_mode(self, mode: str, m5_line_class):
        if mode == "future_resist":
            return [(UsdJpyM5LineOrderStrategy(self.profile), m5_line_class)]
        return [(UsdJpyM5BreakoutLineOrderStrategy(self.profile), m5_line_class)]

    def _reason_func_for_mode(self, mode: str):
        if mode == "immediate":
            return self.profile.immediate_recommended_reasons
        if mode == "future_resist":
            return self.profile.future_resist_recommended_reasons
        if mode == "future_break":
            return self.profile.future_break_recommended_reasons
        raise ValueError(f"Unsupported order mode: {mode}")
