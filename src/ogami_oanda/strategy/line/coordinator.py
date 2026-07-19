from __future__ import annotations

import pandas as pd

from ogami_oanda.domain.market.currency_pair import currency_pair


class LineCandidateCoordinator:
    """Build and select line candidate dictionaries without broker dependencies."""

    def __init__(self, analysis, profile) -> None:
        self.analysis = analysis
        self.pair = getattr(analysis, "pair", "USD_JPY")
        self.pair_info = currency_pair(self.pair)
        self.profile = profile
        self.duplicate_threshold_pips = profile.duplicate_threshold_pips

    def build_line_candidates(self, strategy_lines, current_price, h1_line_class=None, m5_line_class=None, order_mode="limit"):
        candidates = []
        for strategy, line_class in strategy_lines:
            strategy.pair = self.pair
            candidates.extend(strategy.build_candidates(line_class, current_price))
        if order_mode == "immediate":
            for candidate in candidates:
                candidate["line_target_price"] = candidate["target_price"]
                candidate["line_distance_pips"] = candidate.get("distance_pips")
                candidate["target_price"] = self.pair_info.round_price(float(current_price))
                candidate["order_type_override"] = "MARKET"
        if h1_line_class is not None:
            self._add_h1_context(candidates, h1_line_class)
            self._add_previous_peak_line_context(candidates, h1_line_class, "h1_previous_peak_line")
        if m5_line_class is not None:
            self._add_previous_peak_line_context(candidates, m5_line_class, "m5_previous_peak_line")
        return candidates

    def attach_candidate_decision_context(self, candidate, decision_time, order_mode):
        info = self._latest_peak_info(candidate["timeframe"])
        session = self.get_session_info(decision_time)
        candidate.update({
            "session_name": session["session_name"], "session_hour": session["session_hour"], "session_time": session["session_time"],
            "latest_peak_dir": info["direction"], "latest_peak_count": info["count"], "latest_peak_gap": info["gap"],
            "latest_peak_time": info["time"], "latest_peak_strength": info["strength"], "latest_peak_price": info["price"], "latest_peak_rsi": info["rsi"],
            "previous_peak_dir": info["previous_direction"], "previous_peak_count": info["previous_count"], "previous_peak_gap": info["previous_gap"],
            "previous_peak_time": info["previous_time"], "previous_peak_strength": info["previous_strength"], "previous_peak_price": info["previous_price"], "previous_peak_rsi": info["previous_rsi"],
            "order_mode": order_mode,
        })
        return info

    def remove_near_candidates(self, candidates):
        selected = []
        for candidate in sorted(candidates, key=lambda item: item["distance_pips"]):
            is_duplicate = any(
                int(other["direction"]) == int(candidate["direction"])
                and other["line_strategy"] == candidate["line_strategy"]
                and abs(self.pair_info.price_to_pips(float(candidate["line_price"]) - float(other["line_price"]))) <= self.duplicate_threshold_pips
                for other in selected
            )
            if not is_duplicate:
                selected.append(candidate)
        return selected

    def select_line_candidates(self, candidates, rsi_info, decision_time, order_mode, reason_func):
        filtered = []
        for candidate in candidates:
            latest_peak = self.attach_candidate_decision_context(candidate, decision_time, order_mode)
            reasons = reason_func(candidate, rsi_info, latest_peak)
            if not reasons:
                continue
            candidate["recommended_reasons"] = reasons
            candidate["order_mode"] = order_mode
            candidate["memo"] = self._build_condition_memo(candidate, rsi_info, reasons)
            filtered.append(candidate)
        return filtered

    def filter_recommended_candidates(self, candidates, rsi_info, decision_time, order_mode="limit"):
        reason_func = self.profile.immediate_recommended_reasons if order_mode == "immediate" else self.profile.limit_recommended_reasons
        return self.select_line_candidates(candidates, rsi_info, decision_time, order_mode, reason_func)

    @staticmethod
    def get_session_info(decision_time):
        value = pd.to_datetime(decision_time)
        hour = int(value.hour)
        session_name = "morning" if 6 <= hour < 12 else "day" if 12 <= hour < 18 else "night"
        return {"session_name": session_name, "session_hour": hour, "session_time": value.strftime("%Y/%m/%d %H:%M:%S")}

    @staticmethod
    def _build_condition_memo(candidate, rsi_info, reasons):
        line = candidate["line"]
        h1_context = candidate.get("h1_context", {})
        parts = [
            str(candidate.get("order_mode", "line")), candidate["timeframe"], candidate["line_side"], candidate["strategy"].entry_type,
            "peak_dir=" + str(candidate.get("latest_peak_dir")), "peak_count=" + str(candidate.get("latest_peak_count")),
            "peak_rsi=" + str(candidate.get("latest_peak_rsi")), "prev_peak_rsi=" + str(candidate.get("previous_peak_rsi")),
            "strength=" + str(line.get("total_strength")),
            "count=" + str(line.get("count")), "price_gap=" + str(line.get("price_gap")),
            "core_count=" + str(line.get("core_count")),
            "core_strength=" + str(line.get("core_total_strength")), "line_rsi_avg=" + str(line.get("line_peak_rsi_avg")),
            "line_rsi_latest=" + str(line.get("line_peak_rsi_latest")),
        ]

        h1_distance = h1_context.get("h1_nearest_distance_pips")
        h1_strength = h1_context.get("h1_nearest_total_strength")
        h1_side = h1_context.get("h1_nearest_side")
        if h1_distance is not None:
            parts.append("H1_near=" + str(round(float(h1_distance), 1)) + "p")
        if h1_strength is not None:
            parts.append("H1_strength=" + str(h1_strength))
        if h1_side is not None:
            parts.append("H1_side=" + str(h1_side))

        if rsi_info is not None and rsi_info.get("rsi_1") is not None:
            parts.append("RSI=" + str(round(float(rsi_info["rsi_1"]), 1)))
        parts.append("reason=" + " / ".join(reasons))
        return "; ".join(parts)

    def _latest_peak_info(self, timeframe):
        try:
            peaks = self.analysis.peaks_class_hour.peaks_original if timeframe == "h1" else self.analysis.peaks_class.peaks_original
            latest, previous = peaks[0], peaks[1] if len(peaks) > 1 else {}
            return {
                "direction": int(float(latest.get("direction"))), "count": int(latest.get("count") or 0), "gap": latest.get("gap"),
                "time": latest.get("latest_time_jp"), "strength": latest.get("peak_strength"), "price": latest.get("latest_body_peak_price"), "rsi": latest.get("rsi"),
                "previous_direction": previous.get("direction"), "previous_count": previous.get("count"), "previous_gap": previous.get("gap"),
                "previous_time": previous.get("latest_time_jp"), "previous_strength": previous.get("peak_strength"), "previous_price": previous.get("latest_body_peak_price"), "previous_rsi": previous.get("rsi"),
            }
        except (AttributeError, IndexError, TypeError, ValueError):
            return dict.fromkeys(("direction", "count"), 0) | dict.fromkeys(("gap", "time", "strength", "price", "rsi", "previous_direction", "previous_count", "previous_gap", "previous_time", "previous_strength", "previous_price", "previous_rsi"))

    def _add_h1_context(self, candidates, line_class):
        items = self._line_items(line_class)
        for candidate in candidates:
            base_price = float(candidate["line_price"])
            direction = int(candidate["direction"])
            ahead = [item for item in items if (float(item["price"]) - base_price) * direction > 0]
            nearest = self._nearest(items, base_price)
            nearest_ahead = self._nearest(ahead, base_price)
            context = self._line_fields("h1_nearest", nearest, base_price)
            context.update(self._line_fields("h1_ahead", nearest_ahead, base_price))
            context["h1_near_same_line"] = context["h1_nearest_distance_pips"] is not None and context["h1_nearest_distance_pips"] <= self.duplicate_threshold_pips
            context["h1_blocks_trade_direction"] = context["h1_ahead_total_strength"] is not None and context["h1_ahead_total_strength"] >= 10
            candidate["h1_context"] = context

    def _add_previous_peak_line_context(self, candidates, line_class, prefix):
        items = self._line_items(line_class)
        for candidate in candidates:
            previous_price = candidate.get("previous_peak_price")
            context = candidate.setdefault("h1_context", {})
            nearest = self._nearest(items, float(previous_price)) if previous_price is not None else None
            context.update(self._line_fields(prefix, nearest, previous_price))

    def _line_items(self, line_class):
        return [
            {"side": side, "price": self.pair_info.round_price(line["median_price"]), "line": line}
            for side, lines in (("upper", line_class.upper_lines), ("lower", line_class.lower_lines))
            for line in lines
        ]

    @staticmethod
    def _nearest(items, base_price):
        return min(items, key=lambda item: abs(float(item["price"]) - base_price)) if items else None

    def _line_fields(self, prefix, item, base_price):
        if item is None or base_price is None:
            return {f"{prefix}_{field}": None for field in ("side", "price", "distance_pips", "total_strength", "count", "core_total_strength", "is_flipped")}
        line = item["line"]
        return {
            f"{prefix}_side": item["side"], f"{prefix}_price": item["price"],
            f"{prefix}_distance_pips": abs(self.pair_info.price_to_pips(float(item["price"]) - float(base_price))),
            f"{prefix}_total_strength": line.get("total_strength"), f"{prefix}_count": line.get("count"),
            f"{prefix}_core_total_strength": line.get("core_total_strength"), f"{prefix}_is_flipped": line.get("is_flipped_line"),
        }
