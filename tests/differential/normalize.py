from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import numpy as np
import pandas as pd

from .constants import TRACE_SCHEMA_VERSION
from .frame_factory import pair_round_digits


@dataclass
class _BrokerIdNormalizer:
    mapping: dict[str, str]
    next_number: int = 1

    def normalize(self, value: str) -> str:
        existing = self.mapping.get(value)
        if existing is not None:
            return existing
        replacement = f"broker-id-{self.next_number:03d}"
        self.mapping[value] = replacement
        self.next_number += 1
        return replacement


def _is_nan_like(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, float):
        return math.isnan(value)
    if isinstance(value, (np.floating,)):
        return bool(np.isnan(value))
    return False


def _is_datetime_like(value: Any) -> bool:
    return isinstance(value, (datetime, pd.Timestamp, np.datetime64))


def _to_jst_iso(value: Any) -> str:
    if isinstance(value, np.datetime64):
        value = pd.Timestamp(value)
    if isinstance(value, pd.Timestamp):
        timestamp = value
    else:
        timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is None:
        timestamp = timestamp.tz_localize("Asia/Tokyo")
    else:
        timestamp = timestamp.tz_convert("Asia/Tokyo")
    return timestamp.isoformat()


def _looks_like_broker_id(value: str) -> bool:
    if value.startswith("broker-id-"):
        return False
    if value.isdigit() and len(value) >= 1:
        return True
    if value.startswith(("order-", "trade-", "pending-", "tx-")):
        return True
    return False


def _normalize_scalar(value: Any, *, pair: str | None, id_normalizer: _BrokerIdNormalizer) -> Any:
    if _is_nan_like(value):
        return None
    if _is_datetime_like(value):
        return _to_jst_iso(value)

    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.bool_,)):
        return bool(value)

    if isinstance(value, (int, bool)) or value is None:
        return value

    if isinstance(value, str):
        if _looks_like_broker_id(value):
            return id_normalizer.normalize(value)
        return value

    if isinstance(value, (np.floating, float)):
        number = float(value)
        if pair is not None:
            return round(number, pair_round_digits(pair))
        return number

    return value


def _normalize_dataframe_like(value: Any, *, pair: str | None, id_normalizer: _BrokerIdNormalizer) -> Any:
    if not isinstance(value, dict):
        return value
    if set(value.keys()) == {"columns", "rows"} and isinstance(value["columns"], list) and isinstance(value["rows"], list):
        return {
            "columns": [str(column) for column in value["columns"]],
            "rows": [
                [_normalize_value(item, pair=pair, id_normalizer=id_normalizer) for item in row]
                for row in value["rows"]
            ],
        }
    return value


def _normalize_value(value: Any, *, pair: str | None, id_normalizer: _BrokerIdNormalizer) -> Any:
    dataframe_like = _normalize_dataframe_like(value, pair=pair, id_normalizer=id_normalizer)
    if dataframe_like is not value:
        return dataframe_like

    if isinstance(value, dict):
        nested_pair = str(value.get("pair", pair)) if value.get("pair") is not None else pair
        normalized_items = [
            (
                str(key),
                _normalize_value(item, pair=nested_pair, id_normalizer=id_normalizer),
            )
            for key, item in value.items()
        ]
        return {key: val for key, val in sorted(normalized_items, key=lambda item: item[0])}

    if isinstance(value, list):
        return [
            _normalize_value(item, pair=pair, id_normalizer=id_normalizer)
            for item in value
        ]

    if isinstance(value, tuple):
        return [
            _normalize_value(item, pair=pair, id_normalizer=id_normalizer)
            for item in value
        ]

    return _normalize_scalar(value, pair=pair, id_normalizer=id_normalizer)


def normalize_trace(trace: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(trace, dict):
        raise TypeError("trace must be dict")
    pair = trace.get("pair")
    pair_value = str(pair) if isinstance(pair, str) else None
    id_normalizer = _BrokerIdNormalizer(mapping={})
    normalized = _normalize_value(trace, pair=pair_value, id_normalizer=id_normalizer)
    if "runner" in normalized:
        normalized["runner"] = "trace-runner"
    if "schema_version" not in normalized:
        normalized["schema_version"] = TRACE_SCHEMA_VERSION
    return normalized


def dataframe_to_columns_rows(frame: pd.DataFrame) -> dict[str, Any]:
    ordered = frame.copy()
    return {
        "columns": [str(column) for column in ordered.columns],
        "rows": [
            [_value_to_builtin(value) for value in row]
            for row in ordered.itertuples(index=False, name=None)
        ],
    }


def _value_to_builtin(value: Any) -> Any:
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        if np.isnan(value):
            return None
        return float(value)
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if isinstance(value, np.datetime64):
        return pd.Timestamp(value).isoformat()
    if isinstance(value, float) and math.isnan(value):
        return None
    return value
