from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from ogami_oanda.domain.market.currency_pair import currency_pair
from ogami_oanda.strategy.position_sizing import PositionSizingPolicy

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
_CANDIDATE_MODES = ("immediate", "future_resist", "future_break")


@dataclass(frozen=True)
class CandidateDiagnostics:
    raw_counts: Mapping[str, int]
    selected_counts: Mapping[str, int]
    rejected_reasons: Mapping[str, Mapping[str, int]]

    def reject_selected(self, mode: str, reason: str) -> "CandidateDiagnostics":
        selected_counts = dict(self.selected_counts)
        if selected_counts.get(mode, 0) <= 0:
            raise ValueError(f"Cannot reject missing selected candidate for {mode}")
        selected_counts[mode] -= 1
        rejected_reasons = {
            candidate_mode: dict(counts)
            for candidate_mode, counts in self.rejected_reasons.items()
        }
        mode_reasons = rejected_reasons.setdefault(mode, {})
        mode_reasons[reason] = mode_reasons.get(reason, 0) + 1
        return CandidateDiagnostics(
            raw_counts=dict(self.raw_counts),
            selected_counts=selected_counts,
            rejected_reasons=rejected_reasons,
        )


@dataclass(frozen=True)
class CandidateBuildResult:
    candidates: tuple[dict, ...]
    diagnostics: CandidateDiagnostics


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

    def __init__(self, pair: str, profile=None, *, risk_yen: float = 500.0) -> None:
        self.pair = pair
        self.profile = profile or line_strategy_profile_for_pair(pair)
        self.position_sizing = PositionSizingPolicy(risk_yen)

    def __call__(self, context: Mapping[str, object], current_price: float) -> list[dict]:
        return list(self.build_with_diagnostics(context, current_price).candidates)

    def build_with_diagnostics(
        self,
        context: Mapping[str, object],
        current_price: float,
    ) -> CandidateBuildResult:
        raw_candidates = self.build_raw_candidates(context, current_price)
        recommended = self.select_candidates(raw_candidates, context)
        candidates = self.enrich_candidates(
            recommended,
            current_price,
            context=context,
        )
        raw_counts = {
            mode: len(raw_candidates.get(mode, ()))
            for mode in _CANDIDATE_MODES
        }
        recommended_counts = self._counts_by_mode(recommended)
        selected_counts = self._counts_by_mode(candidates)
        rejected_reasons: dict[str, dict[str, int]] = {}
        for mode in _CANDIDATE_MODES:
            rejected: dict[str, int] = {}
            condition_rejected = raw_counts[mode] - recommended_counts[mode]
            if condition_rejected:
                rejected[self._condition_rejection_reason(mode)] = condition_rejected
            session_rejected = recommended_counts[mode] - selected_counts[mode]
            if session_rejected:
                rejected["session_order_permission_false"] = session_rejected
            rejected_reasons[mode] = rejected
        return CandidateBuildResult(
            tuple(candidates),
            CandidateDiagnostics(
                raw_counts=raw_counts,
                selected_counts=selected_counts,
                rejected_reasons=rejected_reasons,
            ),
        )

    @staticmethod
    def _counts_by_mode(candidates: list[dict]) -> dict[str, int]:
        counts = {mode: 0 for mode in _CANDIDATE_MODES}
        for candidate in candidates:
            mode = str(candidate.get("order_mode", "future_break"))
            if mode in counts:
                counts[mode] += 1
        return counts

    def _condition_rejection_reason(self, mode: str) -> str:
        if mode == "immediate":
            return "immediate_conditions_not_met"
        if self.pair == "USD_JPY":
            return "top7_conditions_not_met"
        return "recommendation_conditions_not_met"

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
        for mode in _CANDIDATE_MODES:
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

    def enrich_candidates(
        self,
        selected_candidates: list[dict],
        current_price: float,
        *,
        context: Mapping[str, object] | None = None,
    ) -> list[dict]:
        pair = currency_pair(self.pair)
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
            item["units"] = (
                int(candidate["units"])
                if candidate.get("units") is not None
                else self.position_sizing.units_for(
                    pair,
                    item["lc_pips"],
                    item["units_multiplier"],
                )
            )
            if not self._apply_session_policy(item, context):
                continue
            self._apply_path_short_protection(item, context)
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

    def _apply_session_policy(
        self,
        candidate: dict,
        context: Mapping[str, object] | None,
    ) -> bool:
        policies = self.profile.session_policies
        order_decision_time = (context or {}).get("order_decision_time")
        if order_decision_time is not None:
            session = LineCandidateCoordinator.get_session_info(
                order_decision_time
            )
            candidate.update(session)
        session_name = str(candidate.get("session_name", "night"))
        policy = policies.get(session_name, policies["night"])
        candidate["order_permission"] = bool(policy["order_permission"])
        candidate["session_units_multiplier"] = float(policy["units_multiplier"])
        candidate["session_rr"] = policy["rr"]
        candidate["session_tp_multiplier"] = float(policy["tp_multiplier"])
        candidate["session_lc_multiplier"] = float(policy["lc_multiplier"])
        candidate["session_skip_reason"] = None
        if not candidate["order_permission"]:
            candidate["session_skip_reason"] = "session_order_permission_false"
            return False

        units_multiplier = candidate["session_units_multiplier"]
        if units_multiplier != 1.0:
            original_units = int(candidate["units"])
            adjusted_units = int(original_units * units_multiplier)
            candidate["units"] = (
                adjusted_units
                if adjusted_units != 0 or original_units == 0
                else 1
            )

        effective_lc_pips = float(candidate["lc_pips"])
        effective_tp_pips = float(candidate["tp_pips"])
        if candidate["session_rr"] is not None:
            effective_tp_pips = round(
                effective_lc_pips * float(candidate["session_rr"]),
                1,
            )
            candidate["session_tp_pips"] = effective_tp_pips
        candidate["effective_lc_pips"] = effective_lc_pips
        candidate["effective_tp_pips"] = effective_tp_pips
        return True

    def _apply_path_short_protection(
        self,
        candidate: dict,
        context: Mapping[str, object] | None,
    ) -> None:
        path_distance = (candidate.get("h1_context") or {}).get(
            "h1_path_ahead_1_distance_pips"
        )
        if path_distance is None:
            return
        try:
            distance_pips = float(path_distance)
        except (TypeError, ValueError):
            return

        short_pips = self._path_short_pips(distance_pips, context)
        if (
            short_pips is None
            or float(candidate["effective_tp_pips"]) <= short_pips
        ):
            return
        candidate["path_tp_original_pips"] = float(
            candidate["effective_tp_pips"]
        )
        candidate["path_lc_original_pips"] = float(
            candidate["effective_lc_pips"]
        )
        candidate["effective_tp_pips"] = short_pips
        candidate["effective_lc_pips"] = short_pips
        candidate["path_tp_adjusted"] = True
        candidate["path_tp_adjusted_label"] = (
            f"{self.pair} path1 H1 line short TP"
        )
        candidate["path_tp_pips"] = short_pips
        candidate["path_lc_pips"] = short_pips
        candidate["path_tp_rr"] = 1.0

    def _path_short_pips(
        self,
        distance_pips: float,
        context: Mapping[str, object] | None,
    ) -> float | None:
        if self.pair == "AUD_USD":
            return 5.0 if 0 < distance_pips <= 6 else None
        if self.pair not in {"EUR_USD", "USD_JPY"}:
            return None
        if 0 < distance_pips <= 3:
            if self.pair == "USD_JPY":
                rsi_info = (context or {}).get("rsi_info") or {}
                rsi_1 = rsi_info.get("rsi_1")
                try:
                    if 60 < float(rsi_1) <= 67.5:
                        return 5.0
                except (TypeError, ValueError):
                    pass
            return 3.0
        if distance_pips <= 6:
            return 5.0
        return None

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
