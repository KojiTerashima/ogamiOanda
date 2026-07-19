from __future__ import annotations

import contextlib
import io
import json
from pathlib import Path

import pytest

import classCandleAnalysis
import fAnalysis_order_Main
import fLineAnalysis


def _snapshot_value(value):
    if hasattr(value, "item") and not isinstance(value, (str, bytes, bytearray)):
        try:
            value = value.item()
        except (TypeError, ValueError):
            pass
    if isinstance(value, dict):
        return {key: _snapshot_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_snapshot_value(item) for item in value]
    if isinstance(value, float):
        return round(value, 6)
    return value


def _line_summary(lines):
    keys = (
        "median_price",
        "total_strength",
        "count",
        "ave_strength",
        "is_flipped_line",
        "oldest_time",
        "core_median_price",
        "core_count",
        "core_total_strength",
        "line_touch_count",
        "line_peak_rsi_avg",
        "line_peak_rsi_latest",
        "line_peak_rsi_count",
        "line_history_is_flipped",
        "line_current_role",
        "line_origin_role",
    )
    result = []
    for line in lines:
        item = {}
        for key in keys:
            if key in line:
                value = line[key]
                if isinstance(value, float):
                    value = round(value, 6)
                item[key] = value
        result.append(item)
    return result


def _candidate_summary(candidates):
    result = []
    for candidate in candidates:
        line = candidate["line"]
        item = {
            "timeframe": candidate["timeframe"],
            "line_side": candidate["line_side"],
            "direction": int(candidate["direction"]),
            "line_index": int(candidate["line_index"]),
            "line_price": round(float(candidate["line_price"]), 6),
            "target_price": round(float(candidate["target_price"]), 6),
            "line_strategy": candidate["line_strategy"],
            "distance_pips": round(float(candidate["distance_pips"]), 3),
            "candidate": {
                key: _snapshot_value(value)
                for key, value in candidate.items()
                if key not in {"line", "strategy", "h1_context"}
            },
            "line": {
                "median_price": round(float(line["median_price"]), 6),
                "total_strength": round(float(line.get("total_strength", 0)), 6),
                "count": int(line.get("count") or 0),
                "ave_strength": round(float(line.get("ave_strength") or 0), 6),
                "core_count": int(line.get("core_count") or 0),
                "core_total_strength": round(float(line.get("core_total_strength") or 0), 6),
                "is_flipped_line": line.get("is_flipped_line"),
            },
        }
        if "recommended_reasons" in candidate:
            item["recommended_reasons"] = list(candidate["recommended_reasons"])
        if "order_mode" in candidate:
            item["order_mode"] = candidate["order_mode"]
        if "memo" in candidate:
            item["memo"] = candidate["memo"]
        for key in (
            "session_name",
            "session_hour",
            "latest_peak_dir",
            "latest_peak_count",
            "latest_peak_rsi",
            "previous_peak_rsi",
            "latest_peak_price",
            "previous_peak_price",
        ):
            if key in candidate:
                value = candidate[key]
                if isinstance(value, float):
                    value = round(value, 6)
                item[key] = value
        h1_context = candidate.get("h1_context") or {}
        if h1_context:
            item["h1_context"] = _snapshot_value(h1_context)
        result.append(item)
    return result


def _order_summary(orders):
    result = []
    for order in orders:
        plan = order.exe_order_plan
        item = {
            "name": plan["name"],
            "type": plan["type"],
            "direction": plan["direction"],
            "target_price": round(float(plan["target_price"]), 6),
            "tp_price": round(float(plan["tp_price"]), 6),
            "lc_price": round(float(plan["lc_price"]), 6),
            "priority": int(plan["priority"]),
            "line_strategy": plan.get("line_strategy"),
            "line_side": plan.get("line_side"),
            "line_price": plan.get("line_price"),
            "payload": _snapshot_value(plan["for_api_json"]["order"]),
            "plan": {
                key: _snapshot_value(value)
                for key, value in plan.items()
                if key != "for_api_json"
            },
        }
        if plan.get("recommended_reasons") is not None:
            item["recommended_reasons"] = plan.get("recommended_reasons")
        result.append(item)
    return result


def _analysis_snapshot(pair_name, frames, current_price):
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        candle = classCandleAnalysis.candleAnalysis(
            None,
            pair_name,
            0,
            m5_df_r=frames["M5"].copy(),
            h1_df_r=frames["H1"].copy(),
            m30_df_r=frames["M30"].copy(),
            current_price=float(current_price),
        )
        analysis = fLineAnalysis._LegacyMainAnalysis(candle, None, "inspection")
        profile = analysis.each_pair_line_strategy_profile
        line_class_m5_l = fLineAnalysis.LineStrengthCal(candle, "m5", 60)
        line_class_m5_s = fLineAnalysis.LineStrengthCal(candle, "m5", 30)
        rsi_info = {
            "rsi_1": analysis.df_r_m5.iloc[0].get("RSI"),
            "rsi_2": analysis.df_r_m5.iloc[1].get("RSI"),
            "rsi_3": analysis.df_r_m5.iloc[2].get("RSI"),
        }
        line_context = profile.calculate_line_strength(
            analysis,
            line_class_m5_l,
            line_class_m5_s,
            analysis.line_class_h1_l,
            analysis.line_class_h1_s,
            analysis.current_price,
            analysis.df_r_m5.iloc[0]["time_jp"],
            rsi_info,
        )
        grouped = profile.group_lines(line_context)
        coordinator = grouped["coordinator"]
        selected_immediate = coordinator.select_line_candidates(
            grouped["immediate_candidates"],
            grouped["rsi_info"],
            grouped["decision_time"],
            "immediate",
            profile.immediate_recommended_reasons,
        )
        selected_future_resist = coordinator.select_line_candidates(
            grouped["future_resist_candidates"],
            grouped["rsi_info"],
            grouped["decision_time"],
            "future_resist",
            profile.future_resist_recommended_reasons,
        )
        selected_future_break = coordinator.select_line_candidates(
            grouped["future_break_candidates"],
            grouped["rsi_info"],
            grouped["decision_time"],
            "future_break",
            profile.future_break_recommended_reasons,
        )
        wrapped = fAnalysis_order_Main._LegacyWrapAllAnalysis(candle, None, "inspection")

    return {
        "pair": pair_name,
        "current_price": float(current_price),
        "decision_time": analysis.df_r_m5.iloc[0]["time_jp"],
        "m5_upper_lines": _line_summary(line_class_m5_l.upper_lines),
        "m5_lower_lines": _line_summary(line_class_m5_l.lower_lines),
        "h1_upper_lines": _line_summary(analysis.line_class_h1_l.upper_lines),
        "h1_lower_lines": _line_summary(analysis.line_class_h1_l.lower_lines),
        "immediate_candidates": _candidate_summary(grouped["immediate_candidates"]),
        "future_resist_candidates": _candidate_summary(grouped["future_resist_candidates"]),
        "future_break_candidates": _candidate_summary(grouped["future_break_candidates"]),
        "selected_immediate_candidates": _candidate_summary(selected_immediate),
        "selected_future_resist_candidates": _candidate_summary(selected_future_resist),
        "selected_future_break_candidates": _candidate_summary(selected_future_break),
        "take_position_flag": wrapped.take_position_flag,
        "legacy_orders": _order_summary(wrapped.exe_order_classes),
    }


@pytest.mark.characterization
@pytest.mark.parametrize(
    ("pair_name", "snapshot_name"),
    [
        ("USD_JPY", "analysis_oracle_usd_jpy.json"),
        ("EUR_USD", "analysis_oracle_eur_usd.json"),
        ("AUD_USD", "analysis_oracle_aud_usd.json"),
    ],
)
def test_legacy_analysis_snapshot_matches_fixture(pair_name, snapshot_name, analysis_frame_store):
    snapshot_path = Path(__file__).parent / "fixtures" / snapshot_name
    expected = json.loads(snapshot_path.read_text(encoding="utf-8"))

    actual = _analysis_snapshot(
        pair_name,
        analysis_frame_store[pair_name],
        expected["current_price"],
    )

    assert actual == expected
