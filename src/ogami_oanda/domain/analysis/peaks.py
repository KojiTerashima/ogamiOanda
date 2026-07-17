from __future__ import annotations

import copy
from datetime import datetime, timedelta

import pandas as pd

from ogami_oanda.domain.market.currency_pair import currency_pair


def _time_hms(value: str) -> str:
    return datetime.strptime(value, "%Y/%m/%d %H:%M:%S").strftime("%H:%M:%S")


class PeaksClass:
    """Extract directional candle peaks from a newest-first candle frame."""

    def __init__(self, original_df_r: pd.DataFrame, granularity: str, current_price: float, pair=None) -> None:
        self.s = "     "
        self.max_peak_num = 60
        self.analysis_num = 240
        self.data_hold_peaks = 3
        self.ps_default = 5
        self.ps_most_most_min = 1
        self.ps_most_min = 2
        self.ps_min = 4
        self.ps_most_max = 8
        self.minimum = 0.0000001
        self.pair = pair or currency_pair("USD_JPY")
        self.pip_value = self.pair.pip_value
        self.round_keta = self.pair.round_keta
        self.current_price = current_price
        self._set_granularity_parameters(granularity)

        self.df_r_original = original_df_r
        self.peaks_original: list[dict] = []
        self.peaks_original_with_df: list[dict] = []
        self.skipped_peaks: list[dict] = []
        self.skipped_peaks_hard: list[dict] = []
        self.latest_resistance_line: dict = {}
        self.latest_peak_price = 0
        self.gap_price_and_latest_turn_peak_abs = abs(self.latest_peak_price - self.current_price)
        self.is_big_move_peak = False
        self.is_big_move_candle = False
        self.ave_move = 0
        self.ave_move_for_lc = 0
        self.time_hour = 0
        self.hyper_range = False

        self.df_r = original_df_r[1:]
        self.df_r_copy = copy.deepcopy(self.df_r)
        self.df_r = self.df_r[:self.analysis_num]
        peak_result = self.make_peaks(self.df_r)
        self.peaks_original = peak_result["peaks"]
        self.peaks_original_with_df = peak_result["peaks_with_df"]
        self.skipped_peaks = self.skip_peaks()
        self.skipped_peaks_hard = self.skip_peaks_hard()
        self.recalculation_peak_strength_for_peaks(self.peaks_original)
        self.latest_peak_price = self.peaks_original[0]["peak"]
        self.gap_price_and_latest_turn_peak_abs = abs(self.current_price - self.latest_peak_price)
        self.time_hour = pd.to_datetime(original_df_r.iloc[0]["time_jp"], format="%Y/%m/%d %H:%M:%S").hour
        border_time = datetime.now() - timedelta(hours=1)
        self.peaks_latest = [
            peak
            for peak in self.peaks_original
            if datetime.strptime(peak["latest_time_jp"], "%Y/%m/%d %H:%M:%S") > border_time
        ]

    def _set_granularity_parameters(self, granularity: str) -> None:
        values = {
            "M5": (180, 1, 2, 7, 4.5, 5, 1.2),
            "H1": (240, 5, 7, 7, 7, 7, 4),
            "M30": (240, 5, 15, 20, 25, 25, 4),
        }
        analysis_num, strength_min, strength, strength_second, skip, skip_second, arrow_break = values[granularity]
        self.analysis_num = analysis_num
        self.peak_strength_border_min = self.pips_to_price(strength_min)
        self.peak_strength_border = self.pips_to_price(strength)
        self.peak_strength_border_second = self.pips_to_price(strength_second)
        self.skip_gap_border = self.pips_to_price(skip)
        self.skip_gap_border_second = self.pips_to_price(skip_second)
        self.recent_fluctuation_range = 0.03
        self.fluctuation_gap = self.pips_to_price(30)
        self.fluctuation_count = 3
        self.arrowed_gap = self.pips_to_price(3)
        self.arrowed_break_gap = self.pips_to_price(arrow_break)
        self.check_very_narrow_range_range = self.pips_to_price(7)
        self.dependence_very_large_body_criteria = self.pips_to_price(20)
        self.dependence_large_body_criteria = self.pips_to_price(10)

    def make_peak(self, data_frame: pd.DataFrame) -> dict:
        result = {
            "latest_time_jp": 0, "oldest_time_jp": 0, "direction": 1,
            "latest_body_peak_price": 0, "oldest_body_peak_price": 0,
            "latest_wick_peak_price": 0, "oldest_wick_peak_price": 0,
            "peak_strength": self.ps_default, "rsi": None, "peak_rsi": None,
            "count": 0, "data_size": len(data_frame), "latest_price": 0,
            "oldest_price": 0, "gap": self.minimum, "gap_high_low": self.minimum,
            "gap_close": self.minimum, "body_ave": self.minimum, "move_abs": self.minimum,
            "memo_time": 0, "data": data_frame, "data_remain": data_frame,
            "support_info": {}, "include_large": False, "include_very_large": False,
            "time": 0, "peak": 0, "time_old": 0, "peak_old": 0, "skip_include_num": 0,
        }
        if len(data_frame) <= 1:
            return result

        direction = 0
        count = 0
        for index in range(len(data_frame) - 1):
            tilt = data_frame.iloc[index]["middle_price"] - data_frame.iloc[index + 1]["middle_price"]
            tilt = self.minimum if tilt == 0 else tilt
            tilt_direction = round(tilt / abs(tilt), 0)
            if count == 0:
                direction = tilt_direction
            if tilt_direction == direction:
                count += 1
            else:
                break

        self.df_r_copy = self.df_r_copy[count:]
        peak_frame = data_frame[: count + 1]
        remaining_frame = data_frame[count:]
        if direction == 1:
            latest_body, oldest_body = peak_frame.iloc[0]["inner_high"], peak_frame.iloc[-1]["inner_low"]
            latest_wick, oldest_wick = peak_frame.iloc[0]["high"], peak_frame.iloc[-1]["low"]
        else:
            latest_body, oldest_body = peak_frame.iloc[0]["inner_low"], peak_frame.iloc[-1]["inner_high"]
            latest_wick, oldest_wick = peak_frame.iloc[0]["low"], peak_frame.iloc[-1]["high"]

        gap_close = self.round_price(abs(latest_body - peak_frame.iloc[-1]["close"])) or self.minimum
        gap = self.round_price(abs(latest_body - oldest_body)) or self.minimum
        gap_high_low = self.round_price(abs(latest_wick - oldest_wick)) or self.minimum
        result.update({
            "direction": direction, "count": count + 1, "latest_body_peak_price": latest_body,
            "oldest_body_peak_price": oldest_body, "oldest_time_jp": peak_frame.iloc[-1]["time_jp"],
            "latest_time_jp": peak_frame.iloc[0]["time_jp"], "latest_price": self.current_price,
            "oldest_price": peak_frame.iloc[-1]["open"], "latest_wick_peak_price": latest_wick,
            "oldest_wick_peak_price": oldest_wick, "gap": gap, "gap_high_low": gap_high_low,
            "gap_close": gap_close, "body_ave": self.round_price(data_frame["body_abs"].mean()),
            "move_abs": self.round_price(data_frame["moves"].mean()), "data": peak_frame,
            "data_remain": remaining_frame,
        })
        if "RSI" in peak_frame.columns and pd.notna(peak_frame.iloc[0]["RSI"]):
            result["rsi"] = result["peak_rsi"] = float(peak_frame.iloc[0]["RSI"])
        result["memo_time"] = f"{_time_hms(peak_frame.iloc[-1]['time_jp'])}_{_time_hms(peak_frame.iloc[0]['time_jp'])}"
        body_summary = self.check_large_body_in_peak(result)
        result.update(body_summary)
        result["time"] = result["latest_time_jp"]
        result["peak"] = result["latest_body_peak_price"]
        result["time_old"] = result["oldest_time_jp"]
        result["peak_old"] = result["oldest_body_peak_price"]
        return result

    def make_peaks(self, data_frame: pd.DataFrame) -> dict[str, list[dict]]:
        peaks: list[dict] = []
        peaks_with_df: list[dict] = []
        next_time_peak: dict = {}
        for index in range(222):
            if len(data_frame) == 0:
                break
            peak = self.make_peak(data_frame)
            if (peaks and peaks[-1]["latest_time_jp"] == peak["latest_time_jp"]) or len(peaks) > self.max_peak_num or peak["time"] == 0:
                break
            peak_copy = copy.deepcopy(peak)
            if index <= self.data_hold_peaks:
                columns = ["time_jp", "open", "close", "high", "low", "mid_outer", "inner_high", "inner_low", "body", "body_abs", "bb_range"]
                peak_copy["data"] = peak_copy["data"][[column for column in columns if column in peak_copy["data"].columns]]
            else:
                peak_copy["data"] = pd.DataFrame()
                peak_copy["data_remain"] = pd.DataFrame()
            peaks_with_df.append(peak_copy)

            peak.pop("data", None)
            peak.pop("data_remain", None)
            simple_peak = peak.copy()
            peak["next"] = next_time_peak
            next_time_peak = simple_peak
            if index != 0:
                peaks[-1]["previous_time_peak"] = simple_peak
                peaks[-1]["previous"] = simple_peak
            peaks.append(peak)
            data_frame = data_frame[peak["count"] - 1:]

        for index, peak in enumerate(peaks):
            if index in {0, len(peaks) - 1}:
                continue
            latest, oldest = peaks[index - 1], peaks[index + 1]
            if peak["gap"] <= self.peak_strength_border or (peak["gap"] <= self.peak_strength_border_second and peak["count"] <= 2):
                strength = self.ps_most_most_min if peak["gap"] <= self.peak_strength_border_min else self.ps_most_min
                peak["peak_strength"] = strength
                peaks[index + 1]["peak_strength"] = strength
            elif peak["gap"] / latest["gap"] <= 0.4 and peak["gap"] / oldest["gap"] <= 0.4:
                peak["peak_strength"] = self.ps_most_min
                peaks[index + 1]["peak_strength"] = self.ps_most_min
        return {"peaks": peaks, "peaks_with_df": peaks_with_df}

    def recalculation_peak_strength_for_peaks(self, peaks: list[dict]) -> None:
        max(peaks, key=lambda peak: peak["peak"])["peak_strength"] = self.ps_most_max
        min(peaks, key=lambda peak: peak["peak"])["peak_strength"] = self.ps_most_max
        max_negative = max((peak for peak in peaks if peak["direction"] == -1), key=lambda peak: peak["peak"], default=None)
        min_positive = min((peak for peak in peaks if peak["direction"] == 1), key=lambda peak: peak["peak"], default=None)
        if max_negative is not None:
            max_negative["peak_strength"] = self.ps_most_min
        if min_positive is not None:
            min_positive["peak_strength"] = self.ps_most_min

    def skip_peaks(self) -> list[dict]:
        return self._skip(copy.deepcopy(self.peaks_original), count_border=2)

    def skip_peaks_hard(self) -> list[dict]:
        return self._skip(copy.deepcopy(self.skipped_peaks), count_border=5)

    def _skip(self, peaks: list[dict], count_border: int) -> list[dict]:
        index = 1
        while index < len(peaks) - 1:
            latest, vanished, oldest = peaks[index - 1], peaks[index], peaks[index + 1]
            if vanished["count"] > count_border or vanished["gap"] > self.skip_gap_border:
                index += 1
                continue
            latest_ratio = vanished["gap"] / latest["gap"]
            oldest_ratio = vanished["gap"] / oldest["gap"]
            if latest_ratio >= 0.6 and oldest_ratio >= 0.6:
                index += 1
                continue
            is_skip = (
                (latest_ratio <= 0.35 and oldest_ratio <= 0.6)
                or (oldest_ratio <= 0.35 and latest_ratio <= 0.6)
                or (vanished["gap"] <= self.skip_gap_border_second and latest_ratio <= 0.6 and oldest_ratio <= 0.6)
            )
            if not is_skip or "previous" not in oldest:
                index += 1
                continue
            latest["oldest_body_peak_price"] = oldest["oldest_body_peak_price"]
            latest["oldest_time_jp"] = oldest["oldest_time_jp"]
            latest["oldest_price"] = oldest["oldest_price"]
            latest["count"] = latest["count"] + vanished["count"] + oldest["count"] - 2
            latest["previous"] = oldest["previous"]
            latest["gap"] = self.round_price(abs(latest["latest_body_peak_price"] - oldest["oldest_body_peak_price"]))
            latest["peak_strength"] = self.ps_default
            latest["skip_include_num"] += 1
            del peaks[index:index + 2]
        return peaks

    def cal_target_times_skip_num(self, peaks: list[dict], target_time: str) -> int:
        for peak in peaks:
            if peak["latest_time_jp"] == target_time:
                return peak.get("skip_include_num", 0)
        return 0

    def pips_to_price(self, pips: float) -> float:
        return self.pair.pips_to_price(pips)

    def round_price(self, price: float) -> float:
        return self.pair.round_price(price)

    def check_large_body_in_peak(self, peak: dict) -> dict:
        sorted_frame = peak["data"].sort_values(by="body_abs", ascending=False)
        max_body = sorted_frame["body_abs"].max()
        include_very_large = any(row["body"] >= self.dependence_very_large_body_criteria for _, row in sorted_frame.iterrows())
        count = sum(1 for _ in sorted_frame.iterrows()) if max_body > self.dependence_large_body_criteria else 0
        return {
            "include_large": count / len(sorted_frame) >= 0.65,
            "include_very_large": include_very_large,
            "highest": sorted_frame["high"].max(),
            "lowest": sorted_frame["low"].min(),
        }


def judge_peak_is_belong_peak_group(peaks: list[dict], target_peak: dict) -> bool:
    maximum = max(peaks, key=lambda peak: peak["peak"])
    minimum = min(peaks, key=lambda peak: peak["peak"])
    reference = maximum if target_peak["direction"] == 1 else minimum
    return reference["peak"] - 0.025 <= target_peak["peak"] <= reference["peak"] + 0.025
