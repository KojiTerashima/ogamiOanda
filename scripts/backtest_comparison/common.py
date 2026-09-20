"""Stable records and field-aware differential comparisons."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, is_dataclass
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
import hashlib
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd


PAIRS = ("USD_JPY", "EUR_USD", "AUD_USD")
START = "2024-09-01T00:00:00+00:00"
PILOT_END = "2024-09-08T00:00:00+00:00"
MONTH_END = "2024-10-01T00:00:00+00:00"
PRICES = {"target_price", "take_profit_price", "stop_loss_price", "entry_price", "exit_price"}
EXACT = {"units", "direction", "order_timeout_min", "trade_timeout_min", "priority", "count"}


def plain(value):
    if isinstance(value, pd.DataFrame):
        return {"columns": list(value.columns), "rows": plain(value.to_dict("records"))}
    if isinstance(value, pd.Series):
        return plain(value.to_dict())
    if isinstance(value, np.generic):
        return plain(value.item())
    if value is pd.NaT or value is pd.NA:
        return None
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, (datetime, date, pd.Timestamp)):
        return value.isoformat()
    if is_dataclass(value):
        return plain(asdict(value))
    if isinstance(value, Mapping):
        return {str(k): plain(v) for k, v in sorted(value.items(), key=lambda item: str(item[0]))}
    if isinstance(value, (list, tuple, np.ndarray)):
        return [plain(v) for v in value]
    raise TypeError(f"unsupported comparison record: {type(value).__name__}")


def encoded(value):
    return json.dumps(plain(value), sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(encoded(value)).hexdigest()


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(plain(value), sort_keys=True, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(payload, encoding="utf-8")
    temporary.replace(path)


class JsonLines:
    def __init__(self, path):
        self.stream = Path(path).open("x", encoding="utf-8")
        self.count = 0
        self.hasher = hashlib.sha256()

    def add(self, record):
        payload = encoded(record) + b"\n"
        self.stream.write(payload.decode())
        self.stream.flush()
        self.hasher.update(payload)
        self.count += 1

    def close(self):
        self.stream.close()


def differences(left, right, pair, path=""):
    """No tolerance for categories; bounded tolerances for actual numeric values."""
    left, right = plain(left), plain(right)
    if isinstance(left, dict) and isinstance(right, dict):
        result = []
        for key in sorted(left.keys() | right.keys()):
            child = f"{path}.{key}" if path else key
            if key not in left or key not in right:
                result.append({"field": child, "main": left.get(key), "ogami": right.get(key), "kind": "missing"})
            else:
                result.extend(differences(left[key], right[key], pair, child))
        return result
    if isinstance(left, list) and isinstance(right, list):
        result = []
        for i in range(max(len(left), len(right))):
            child = f"{path}[{i}]"
            if i >= len(left) or i >= len(right):
                result.append({"field": child, "main": left[i] if i < len(left) else None,
                               "ogami": right[i] if i < len(right) else None, "kind": "missing"})
            else:
                result.extend(differences(left[i], right[i], pair, child))
        return result
    leaf = path.rsplit(".", 1)[-1]
    numeric = (isinstance(left, (int, float)) and not isinstance(left, bool)
               and isinstance(right, (int, float)) and not isinstance(right, bool))
    if numeric and leaf in PRICES:
        quantum = Decimal("0.001" if pair == "USD_JPY" else "0.00001")
        same = Decimal(str(left)).quantize(quantum, rounding=ROUND_HALF_UP) == Decimal(str(right)).quantize(quantum, rounding=ROUND_HALF_UP)
    elif numeric and leaf not in EXACT:
        same = math.isclose(left, right, rel_tol=0 if leaf == "pnl_quote" else 1e-9,
                            abs_tol=1e-6 if leaf == "pnl_quote" else 1e-9)
    else:
        same = type(left) is type(right) and left == right
    return [] if same else [{"field": path, "main": left, "ogami": right, "kind": "value"}]


def candidate_key(candidate, ordinal):
    """Prices and generated order IDs MUST NOT hide price-only differences."""
    meta = candidate.get("metadata", {})
    return (meta.get("source", "resistance_breakout"), meta.get("line_timeframe", "M30"),
            meta.get("line_side"), meta.get("line_oldest_time"), ordinal)


def compare_candidates(left, right, pair):
    # Native source returns a deterministic ranked list. Keep occurrences, including duplicates.
    a = {candidate_key(c, i): c for i, c in enumerate(left)}
    b = {candidate_key(c, i): c for i, c in enumerate(right)}
    result = []
    for key in sorted(a.keys() | b.keys(), key=str):
        if key not in a or key not in b:
            result.append({"candidate": key, "kind": "main_only" if key in a else "ogami_only",
                           "main": a.get(key), "ogami": b.get(key)})
        else:
            for difference in differences(a[key], b[key], pair):
                result.append({"candidate": key, **difference})
    return result
