from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from itertools import groupby
from statistics import median

import pandas as pd

from ogami_oanda.domain.market.currency_pair import currency_pair


@dataclass
class LineStrengthResult:
    pair: str
    foot: str
    current_price: float
    latest_peak_dir: int
    filtered_peaks: list[dict]
    upper_lines: list[dict]
    lower_lines: list[dict]
    tp_lines: list[dict]
    lc_lines: list[dict]
    all_lines: list[dict]


class LineGrouper:
    """Pure price-band grouping for Peak dictionaries."""

    def __init__(self, pair_name: str, max_line_price_gap_pips: float | None = None) -> None:
        self.pair = currency_pair(pair_name)
        self.max_line_price_gap_pips = max_line_price_gap_pips

    def make_same_price_group(
        self,
        peaks: list[dict],
        upper_lower: int,
        target_price: float,
        threshold: float = 3,
        direction_filter: int | None = None,
        sort_direction: int = -1,
    ) -> list[dict]:
        target_price_pips = self.pair.price_to_pips(target_price)
        filtered = [
            peak
            for peak in peaks
            if (float(peak["latest_body_peak_price"]) < target_price if upper_lower == -1 else float(peak["latest_body_peak_price"]) >= target_price)
            and (direction_filter is None or peak["direction"] == direction_filter)
        ]
        if not filtered:
            return []

        sorted_peaks = sorted(filtered, key=lambda peak: float(peak["latest_body_peak_price"]), reverse=True)
        used_indices: set[int] = set()
        results: list[dict] = []
        for index, peak in enumerate(sorted_peaks):
            if index in used_indices:
                continue
            center_price = float(peak["latest_body_peak_price"])
            center_pips = self.pair.price_to_pips(center_price)
            group_indices = [
                candidate_index
                for candidate_index, candidate in enumerate(sorted_peaks)
                if candidate_index not in used_indices
                and abs(self.pair.price_to_pips(float(candidate["latest_body_peak_price"])) - center_pips) <= threshold
            ]
            group_items = [sorted_peaks[candidate_index] for candidate_index in group_indices]
            if group_items:
                results.append(self._group_record(group_items, target_price, target_price_pips, threshold, center_pips))
                used_indices.update(group_indices)

        return sorted(results, key=lambda result: result["median_price"], reverse=sort_direction == -1)

    def make_same_price_group_core_first(
        self,
        peaks: list[dict],
        upper_lower: int,
        target_price: float,
        threshold: float = 3,
        direction_filter: int | None = None,
        sort_direction: int = -1,
        core_strength: float = 5,
        attach_strength: float = 2,
    ) -> list[dict]:
        filtered = [
            peak
            for peak in peaks
            if (float(peak["latest_body_peak_price"]) < target_price if upper_lower == -1 else float(peak["latest_body_peak_price"]) >= target_price)
            and (direction_filter is None or peak["direction"] == direction_filter)
        ]
        core_peaks = [peak for peak in filtered if float(peak.get("peak_strength", 0)) >= core_strength]
        if not core_peaks:
            return []
        results = self.make_same_price_group(core_peaks, upper_lower, target_price, threshold, direction_filter, sort_direction)
        for result in results:
            result["core_median_price"] = result["median_price"]
            result["core_count"] = result["count"]
            result["core_total_strength"] = result["total_strength"]

        attached = set()
        for peak in (peak for peak in filtered if float(peak.get("peak_strength", 0)) <= attach_strength):
            nearest = self._nearest_group(results, peak, threshold)
            peak_id = (peak.get("latest_time_jp"), peak.get("latest_body_peak_price"), peak.get("direction"))
            if nearest is not None and peak_id not in attached and self.can_add_peak_to_line(nearest, peak):
                attached.add(peak_id)
                nearest["prices_info"].append(peak)
                self.refresh_line_group(nearest, target_price, threshold)
        return sorted(results, key=lambda result: result["median_price"], reverse=sort_direction == -1)

    def can_add_peak_to_line(self, result: dict, peak: dict) -> bool:
        if self.max_line_price_gap_pips is None:
            return True
        prices = [float(item["latest_body_peak_price"]) for item in result.get("prices_info", [])]
        prices.append(float(peak["latest_body_peak_price"]))
        return self.pair.price_to_pips(max(prices) - min(prices)) <= self.max_line_price_gap_pips

    def refresh_line_group(self, result: dict, target_price: float, threshold: float) -> None:
        refreshed = self._group_record(
            result["prices_info"],
            target_price,
            self.pair.price_to_pips(target_price),
            threshold,
            self.pair.price_to_pips(float(result["core_median_price"])),
            include_rsi=True,
        )
        result.update(refreshed)

    def _nearest_group(self, results: list[dict], peak: dict, threshold: float) -> dict | None:
        peak_pips = self.pair.price_to_pips(float(peak["latest_body_peak_price"]))
        matches = [
            (abs(peak_pips - self.pair.price_to_pips(float(result["core_median_price"]))), result)
            for result in results
            if abs(peak_pips - self.pair.price_to_pips(float(result["core_median_price"]))) <= threshold
        ]
        return min(matches, default=(None, None), key=lambda match: match[0])[1]

    def _group_record(
        self,
        items: list[dict],
        target_price: float,
        target_pips: float,
        threshold: float,
        range_center_pips: float,
        include_rsi: bool = False,
    ) -> dict:
        items = sorted(items, key=lambda item: datetime.strptime(item["latest_time_jp"], "%Y/%m/%d %H:%M:%S"), reverse=True)
        prices = [float(item["latest_body_peak_price"]) for item in items]
        prices_pips = [self.pair.price_to_pips(price) for price in prices]
        times = [datetime.strptime(item["latest_time_jp"], "%Y/%m/%d %H:%M:%S") for item in items]
        strengths = [float(item["peak_strength"]) for item in items]
        rsi_values = [float(item["rsi"]) for item in items if item.get("rsi") is not None and not pd.isna(item["rsi"])]
        median_price = median(prices)
        result = {
            "median_price": median_price,
            "median_p": self.pair.price_to_pips(abs(target_price - median_price)),
            "median": abs(target_pips - median(prices_pips)),
            "total_strength": sum(strengths),
            "count": len(items),
            "ave_strength": round(sum(strengths) / len(items), 1) if items else 0,
            "prices": prices,
            "price_gap": self.pair.price_to_pips(max(prices) - min(prices)),
            "prices_info": items,
            "dirs": [item["direction"] for item in items],
            "dirs_grouped": [sum(group) for _, group in groupby(item["direction"] for item in items)],
            "range_min": range_center_pips - threshold,
            "range_max": range_center_pips + threshold,
            "newest_time": max(times).strftime("%Y/%m/%d %H:%M:%S"),
            "oldest_time": min(times).strftime("%Y/%m/%d %H:%M:%S"),
        }
        if include_rsi:
            result["line_peak_rsi_count"] = len(rsi_values)
            result["line_peak_rsi_avg"] = round(sum(rsi_values) / len(rsi_values), 1) if rsi_values else None
            result["line_peak_rsi_latest"] = rsi_values[0] if rsi_values else None
        return result


class LineStrengthCalculator:
    """Construct legacy-compatible line classes from pure peak and candle inputs."""

    _THRESHOLD_BY_FOOT = {"m5": 1, "h1": 2.5, "m30": 3}

    def __init__(self, pair_name: str) -> None:
        self.pair_name = pair_name
        self.pair = currency_pair(pair_name)

    def calculate(
        self,
        *,
        foot: str,
        peaks: list[dict],
        frame: pd.DataFrame,
        current_price: float,
        current_time: str,
        time_before_foot_count: int = 30,
    ) -> LineStrengthResult:
        if foot not in self._THRESHOLD_BY_FOOT:
            raise ValueError(f"Unsupported line timeframe: {foot}")
        if frame.empty or not peaks:
            return LineStrengthResult(
                self.pair_name,
                foot,
                float(current_price),
                0,
                [],
                [],
                [],
                [],
                [],
                [],
            )

        threshold = self._THRESHOLD_BY_FOOT[foot] if foot == "m5" else 3
        max_gap = 2 if foot == "m5" else None
        window = frame.iloc[:time_before_foot_count].copy()
        if window.empty:
            window = frame.copy()
        time_format = "%Y/%m/%d %H:%M:%S"
        oldest_time = datetime.strptime(window.iloc[-1]["time_jp"], time_format)
        frame_current_time = datetime.strptime(frame.iloc[0]["time_jp"], time_format)
        window_hours = (frame_current_time - oldest_time).total_seconds() / 3600
        border_time = datetime.strptime(current_time, time_format) - pd.Timedelta(hours=window_hours)
        latest_peak = peaks[0]
        filtered_peaks = [
            peak
            for peak in peaks
            if datetime.strptime(peak["latest_time_jp"], time_format) > border_time
            and not self._same_peak(peak, latest_peak)
            and float(peak.get("peak_strength", 0)) >= 0
        ]
        latest_peak_dir = int(float(latest_peak["direction"]))
        base_price = float(current_price) - latest_peak_dir * self.pair.pips_to_price(1)
        grouper = LineGrouper(self.pair_name, max_line_price_gap_pips=max_gap)
        upper_lines = grouper.make_same_price_group_core_first(
            filtered_peaks,
            1,
            base_price,
            threshold=threshold,
            sort_direction=1,
        )
        lower_lines = grouper.make_same_price_group_core_first(
            filtered_peaks,
            -1,
            base_price,
            threshold=threshold,
            sort_direction=-1,
        )
        tp_lines, lc_lines = (upper_lines, lower_lines) if latest_peak_dir == 1 else (lower_lines, upper_lines)
        all_lines = self._combine_all_lines(upper_lines, lower_lines, latest_peak_dir)
        for line in all_lines:
            self._add_line_role_history(line, window, current_time)
            self._add_line_flip_marker(line)
        return LineStrengthResult(
            self.pair_name,
            foot,
            float(current_price),
            latest_peak_dir,
            filtered_peaks,
            upper_lines,
            lower_lines,
            tp_lines,
            lc_lines,
            all_lines,
        )

    @staticmethod
    def _same_peak(first: dict, second: dict) -> bool:
        return (
            first.get("latest_time_jp") == second.get("latest_time_jp")
            and first.get("latest_body_peak_price") == second.get("latest_body_peak_price")
            and first.get("direction") == second.get("direction")
        )

    @staticmethod
    def _combine_all_lines(upper_lines: list[dict], lower_lines: list[dict], latest_peak_dir: int) -> list[dict]:
        if latest_peak_dir == 1:
            return list(reversed(upper_lines)) + [{**line, "median": -line["median"]} for line in lower_lines]
        return list(reversed(lower_lines)) + [{**line, "median": -line["median"]} for line in upper_lines]

    @staticmethod
    def _add_line_flip_marker(line: dict) -> None:
        directions = line["dirs_grouped"]
        line["is_flipped_line"] = bool(
            line["count"] >= 3
            and len(directions) >= 2
            and directions[0] * directions[1] < 0
            and line["prices_info"][0]["peak_strength"] > 2
            and abs(directions[1]) >= 2
        )
        line["is_flipped_line_st"] = 0

    def _add_line_role_history(self, line: dict, frame: pd.DataFrame, current_time: str) -> None:
        time_format = "%Y/%m/%d %H:%M:%S"
        peaks = line.get("prices_info") or []
        line.update({
            "line_break_threshold_pips": 2,
            "line_origin_peak_dir": None,
            "line_origin_role": None,
            "line_current_role": None,
            "line_history_is_flipped": False,
            "line_flip_count": 0,
            "line_latest_flip_time": None,
            "line_latest_flip_elapsed_minutes": None,
            "line_latest_flip_bars": None,
            "line_latest_touch_peak_dir": None,
            "line_latest_touch_time": None,
            "line_latest_touch_elapsed_minutes": None,
            "line_latest_touch_bars": None,
            "line_touch_count": len(peaks),
            "line_single_role": None,
            "line_single_role_last_touch_time": None,
            "line_single_role_last_touch_elapsed_minutes": None,
            "line_single_role_last_touch_bars": None,
        })
        if not peaks or frame.empty:
            return

        current = datetime.strptime(current_time, time_format)
        origin_peak = peaks[-1]
        latest_peak = peaks[0]
        origin_dir = int(origin_peak["direction"])
        origin_time = datetime.strptime(origin_peak["latest_time_jp"], time_format)
        latest_touch_time = datetime.strptime(latest_peak["latest_time_jp"], time_format)
        origin_role = "resistance" if origin_dir == 1 else "support"
        line["line_origin_peak_dir"] = origin_dir
        line["line_origin_role"] = origin_role
        line["line_latest_touch_peak_dir"] = int(latest_peak["direction"])
        line["line_latest_touch_time"] = latest_touch_time.strftime(time_format)
        line["line_latest_touch_elapsed_minutes"] = round(max((current - latest_touch_time).total_seconds(), 0) / 60, 1)

        candles = frame.copy()
        candles["line_event_time"] = pd.to_datetime(candles["time_jp"], format=time_format)
        candles = candles[(candles["line_event_time"] > origin_time) & (candles["line_event_time"] <= current)].sort_values("line_event_time")
        line["line_latest_touch_bars"] = int((candles["line_event_time"] > latest_touch_time).sum())

        threshold_price = self.pair.pips_to_price(2)
        stable_side = -1 if origin_role == "resistance" else 1
        flip_times = []
        for candle in candles.itertuples(index=False):
            close = float(candle.close)
            if close > float(line["median_price"]) + threshold_price:
                close_side = 1
            elif close < float(line["median_price"]) - threshold_price:
                close_side = -1
            else:
                continue
            if close_side != stable_side:
                flip_times.append(candle.line_event_time)
                stable_side = close_side

        flip_count = len(flip_times)
        current_role = origin_role if flip_count % 2 == 0 else ("support" if origin_role == "resistance" else "resistance")
        line["line_current_role"] = current_role
        line["line_history_is_flipped"] = current_role != origin_role
        line["line_flip_count"] = flip_count
        if flip_count == 0:
            line["line_single_role"] = origin_role
            line["line_single_role_last_touch_time"] = line["line_latest_touch_time"]
            line["line_single_role_last_touch_elapsed_minutes"] = line["line_latest_touch_elapsed_minutes"]
            line["line_single_role_last_touch_bars"] = line["line_latest_touch_bars"]
        else:
            latest_flip_time = flip_times[-1]
            line["line_latest_flip_time"] = latest_flip_time.strftime(time_format)
            line["line_latest_flip_elapsed_minutes"] = round(max((current - latest_flip_time).total_seconds(), 0) / 60, 1)
            line["line_latest_flip_bars"] = int((candles["line_event_time"] > latest_flip_time).sum())
