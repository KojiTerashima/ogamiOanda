from __future__ import annotations

from datetime import datetime
from itertools import groupby
from statistics import median

import pandas as pd

from ogami_oanda.domain.market.currency_pair import currency_pair


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
