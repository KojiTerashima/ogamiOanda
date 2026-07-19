from __future__ import annotations

from typing import Mapping

import pandas as pd

from ogami_oanda.domain.analysis.candle_meta import CandleMeta
from ogami_oanda.domain.analysis.lines import LineStrengthCalculator


def build_line_candidate_context(
    pair: str,
    frames: Mapping[str, pd.DataFrame],
    peaks: Mapping[str, object],
    current_price: float,
    decision_time: str,
) -> dict[str, object]:
    """Build the pure line-analysis context required by LineCandidateBuilder."""

    calculator = LineStrengthCalculator(pair)
    m5_frame = frames["M5"].iloc[1:].copy()
    h1_frame = frames["H1"].copy()
    current_time = frames["M5"].iloc[0]["time_jp"]
    rsi_info = _rsi_info(frames["M5"], frames["H1"])
    line_class_m5_l = calculator.calculate(
        foot="m5",
        peaks=peaks["M5"].peaks_original,
        frame=m5_frame,
        current_price=current_price,
        current_time=current_time,
        time_before_foot_count=60,
    )
    line_class_m5_s = calculator.calculate(
        foot="m5",
        peaks=peaks["M5"].peaks_original,
        frame=m5_frame,
        current_price=current_price,
        current_time=current_time,
        time_before_foot_count=30,
    )
    line_class_h1_l = calculator.calculate(
        foot="h1",
        peaks=peaks["H1"].peaks_original,
        frame=h1_frame,
        current_price=current_price,
        current_time=current_time,
        time_before_foot_count=65,
    )
    line_class_h1_s = calculator.calculate(
        foot="h1",
        peaks=peaks["H1"].peaks_original,
        frame=h1_frame,
        current_price=current_price,
        current_time=current_time,
        time_before_foot_count=30,
    )
    return {
        "decision_time": decision_time,
        "order_decision_time": current_time,
        "move_ave": CandleMeta(peaks["M5"], "M5").cal_move_ave(1),
        "rsi_info": rsi_info,
        "peaks": peaks,
        "line_class_m5_main": line_class_m5_l,
        "line_class_m5_sub": line_class_m5_s,
        "line_class_h1_main": line_class_h1_l,
        "line_class_h1_sub": line_class_h1_s,
    }


def _rsi_info(m5_frame: pd.DataFrame, h1_frame: pd.DataFrame) -> dict[str, object]:
    upper_border = 67.5
    lower_border = 30
    m5 = _timeframe_rsi_info("", m5_frame, upper_border, lower_border)
    m5["rsi_upper_border"] = upper_border
    m5["rsi_lower_border"] = lower_border
    return m5 | _timeframe_rsi_info("h1_", h1_frame, upper_border, lower_border)


def _timeframe_rsi_info(
    prefix: str,
    frame: pd.DataFrame,
    upper_border: float,
    lower_border: float,
) -> dict[str, object]:
    keys = {
        f"{prefix}rsi_1": None,
        f"{prefix}rsi_2": None,
        f"{prefix}rsi_3": None,
        f"{prefix}rsi_time_1": None,
        f"{prefix}rsi_time_2": None,
        f"{prefix}rsi_time_3": None,
        f"{prefix}rsi_is_high": None,
        f"{prefix}rsi_is_low": None,
    }
    if len(frame) <= 3 or "RSI" not in frame.columns:
        return keys

    first, second, third = frame.iloc[1], frame.iloc[2], frame.iloc[3]
    rsi_1 = first.get("RSI")
    return keys | {
        f"{prefix}rsi_1": rsi_1,
        f"{prefix}rsi_2": second.get("RSI"),
        f"{prefix}rsi_3": third.get("RSI"),
        f"{prefix}rsi_time_1": first.get("time_jp"),
        f"{prefix}rsi_time_2": second.get("time_jp"),
        f"{prefix}rsi_time_3": third.get("time_jp"),
        f"{prefix}rsi_is_high": rsi_1 >= upper_border,
        f"{prefix}rsi_is_low": rsi_1 <= lower_border,
    }
