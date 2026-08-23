from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from datetime import datetime
from enum import Enum
from typing import Any

import numpy as np
import pandas as pd

def builtin_value(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        return {
            str(key): builtin_value(item)
            for key, item in sorted(value.items(), key=lambda item: str(item[0]))
        }
    if isinstance(value, (list, tuple)):
        return [builtin_value(item) for item in value]
    if isinstance(value, (set, frozenset)):
        normalized = [builtin_value(item) for item in value]
        return sorted(
            normalized,
            key=lambda item: json.dumps(
                item,
                ensure_ascii=True,
                sort_keys=True,
            ),
        )
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return None if np.isnan(value) else float(value)
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, float) and np.isnan(value):
        return None
    return value


def frame_indicator_summary(frame: pd.DataFrame) -> dict[str, Any]:
    prepared = frame.copy()
    if "time_jp_dt" not in prepared.columns and "time_jp" in prepared.columns:
        prepared.insert(
            1,
            "time_jp_dt",
            pd.to_datetime(prepared["time_jp"]),
        )
    columns = [str(column) for column in prepared.columns]
    return {
        "row_count": len(prepared),
        "series": {
            column: [builtin_value(value) for value in prepared[column].tolist()]
            for column in columns
        },
    }


def frame_store_summary(frames: Mapping[str, pd.DataFrame]) -> dict[str, Any]:
    return {
        timeframe: frame_indicator_summary(frames[timeframe])
        for timeframe in ("M5", "H1", "M30", "S5")
        if timeframe in frames
    }


def peak_summary(peaks: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [builtin_value(peak) for peak in peaks]


def peaks_store_summary(peaks: Mapping[str, object]) -> dict[str, Any]:
    return {
        timeframe: peak_summary(getattr(peaks[timeframe], "peaks_original", ()))
        for timeframe in ("M5", "H1", "M30")
        if timeframe in peaks
    }


def line_summary(lines: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [builtin_value(line) for line in lines]


def line_store_summary(context: Mapping[str, object]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for prefix, key in (
        ("m5", "line_class_m5_main"),
        ("h1", "line_class_h1_main"),
    ):
        line_class = context[key]
        result[f"{prefix}_upper"] = line_summary(getattr(line_class, "upper_lines", ()))
        result[f"{prefix}_lower"] = line_summary(getattr(line_class, "lower_lines", ()))
    return result


def candidate_summary(candidates: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    result = []
    for candidate in candidates:
        item = {
            str(key): builtin_value(value)
            for key, value in sorted(candidate.items())
            if key != "strategy"
        }
        strategy = candidate.get("strategy")
        if strategy is not None:
            item["strategy"] = {
                "class": type(strategy).__name__,
                "settings": object_settings(strategy, exclude={"profile"}),
                "profile_class": type(getattr(strategy, "profile", None)).__name__,
            }
        result.append(item)
    return result


def object_settings(
    value: object,
    *,
    exclude: set[str] | None = None,
) -> dict[str, Any]:
    excluded = exclude or set()
    settings: dict[str, Any] = {}
    for cls in reversed(type(value).__mro__):
        for key, item in vars(cls).items():
            if (
                key.startswith("_")
                or key in excluded
                or isinstance(item, (classmethod, staticmethod, property))
                or callable(item)
            ):
                continue
            settings[str(key)] = builtin_value(item)
    for key, item in vars(value).items():
        if key not in excluded:
            settings[str(key)] = builtin_value(item)
    return {
        key: settings[key]
        for key in sorted(settings)
    }


def strategy_profiles_summary(
    candidates: Mapping[str, Sequence[Mapping[str, Any]]],
) -> dict[str, Any]:
    profiles: dict[str, Any] = {}
    for mode in ("immediate", "future_resist", "future_break"):
        for candidate in candidates.get(mode, ()):
            strategy = candidate.get("strategy")
            profile = getattr(strategy, "profile", None)
            if profile is None:
                continue
            profile_name = type(profile).__name__
            profiles.setdefault(profile_name, object_settings(profile))
    return {
        key: profiles[key]
        for key in sorted(profiles)
    }


def candidates_store_summary(
    raw_candidates: Mapping[str, Sequence[Mapping[str, Any]]],
    selected_candidates: Mapping[str, Sequence[Mapping[str, Any]]],
    enriched_candidates: Mapping[
        str,
        Sequence[tuple[Mapping[str, Any], Mapping[str, Any]]],
    ] | None = None,
) -> dict[str, Any]:
    result = {
        "raw": {
            mode: candidate_summary(raw_candidates.get(mode, ()))
            for mode in ("immediate", "future_resist", "future_break")
        },
        "selected": {
            mode: candidate_summary(selected_candidates.get(mode, ()))
            for mode in ("immediate", "future_resist", "future_break")
        },
    }
    if enriched_candidates is not None:
        result["enriched"] = {
            mode: [
                {
                    "candidate": candidate_summary((candidate,))[0],
                    "plan": plan_summary(plan),
                }
                for candidate, plan in enriched_candidates.get(mode, ())
            ]
            for mode in ("immediate", "future_resist", "future_break")
        }
    return result


_NON_METADATA_PLAN_KEYS = {
    "candle_analysis_class",
    "for_api_json",
    "linkage_order_classes",
    "pair",
    "direction",
    "type",
    "target_price",
    "tp_price",
    "lc_price",
    "tp_range",
    "lc_range",
    "units",
    "name",
    "priority",
    "order_timeout_min",
    "trade_timeout_min",
    "lc_change",
}


def _semantic_metadata(plan: Mapping[str, Any]) -> dict[str, Any]:
    return {
        str(key): builtin_value(value)
        for key, value in sorted(plan.items())
        if key not in _NON_METADATA_PLAN_KEYS
    }


def current_semantic_plan(
    intent: object,
    legacy_plan: Mapping[str, Any],
) -> dict[str, Any]:
    result = dict(legacy_plan)
    metadata = getattr(intent, "metadata")
    for key, value in metadata.items():
        if key != "legacy_plan_metadata" and key not in _NON_METADATA_PLAN_KEYS:
            result.setdefault(str(key), value)
    return result


def current_intent_metadata_loss(
    intent: object,
    adapter_plan: Mapping[str, Any],
) -> dict[str, Any]:
    metadata = getattr(intent, "metadata")
    return {
        str(key): builtin_value(value)
        for key, value in sorted(metadata.items())
        if key != "legacy_plan_metadata" and key not in adapter_plan
    }


def intent_summary(
    intent: object,
    *,
    legacy_plan: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "pair": str(getattr(intent, "pair")),
        "direction": builtin_value(getattr(intent, "direction")),
        "order_type": builtin_value(getattr(intent, "order_type")),
        "target": builtin_value(getattr(intent, "target")),
        "target_is_price": bool(getattr(intent, "target_is_price")),
        "take_profit": builtin_value(getattr(intent, "take_profit")),
        "take_profit_is_price": bool(getattr(intent, "take_profit_is_price")),
        "stop_loss": builtin_value(getattr(intent, "stop_loss")),
        "stop_loss_is_price": bool(getattr(intent, "stop_loss_is_price")),
        "units": int(getattr(intent, "units")),
        "name": str(getattr(intent, "name")),
        "priority": int(getattr(intent, "priority")),
        "order_timeout_min": int(getattr(intent, "order_timeout_min")),
        "trade_timeout_min": int(getattr(intent, "trade_timeout_min")),
        "lc_change": builtin_value(getattr(intent, "lc_change")),
        "metadata": _semantic_metadata(legacy_plan),
    }


def legacy_intent_summary(plan: Mapping[str, Any]) -> dict[str, Any]:
    pair = str(plan.get("pair", "USD_JPY"))
    direction = int(plan["direction"])
    order_type = str(plan["type"])
    target_price = float(plan["target_price"])
    tp_price = float(plan["tp_price"])
    lc_price = float(plan["lc_price"])
    return {
        "pair": pair,
        "direction": direction,
        "order_type": order_type,
        "target": 0 if order_type == "MARKET" else target_price,
        "target_is_price": order_type != "MARKET",
        "take_profit": abs(tp_price - target_price),
        "take_profit_is_price": False,
        "stop_loss": abs(target_price - lc_price),
        "stop_loss_is_price": False,
        "units": int(plan["units"]),
        "name": str(plan["name"]),
        "priority": int(plan.get("priority", 0)),
        "order_timeout_min": int(plan.get("order_timeout_min", 60)),
        "trade_timeout_min": int(plan.get("trade_timeout_min", 240)),
        "lc_change": builtin_value(plan.get("lc_change", ())),
        "metadata": _semantic_metadata(plan),
    }


def plan_summary(plan: Mapping[str, Any]) -> dict[str, Any]:
    return {
        str(key): builtin_value(value)
        for key, value in sorted(plan.items())
        if key
        not in {
            "candle_analysis_class",
            "for_api_json",
            "linkage_order_classes",
        }
    }
