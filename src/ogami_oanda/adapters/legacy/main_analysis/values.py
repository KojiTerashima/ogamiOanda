"""Detach upstream values before disposing their private module namespace."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import fields, is_dataclass
from datetime import date, datetime
from math import isfinite

import numpy as np
import pandas as pd


def plain(value, _parents=None):
    if isinstance(value, (float, np.floating)) and not isfinite(value):
        return None
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, np.generic):
        return plain(value.item(), _parents)
    if isinstance(value, (datetime, date, pd.Timestamp)):
        return value.isoformat()
    if isinstance(value, pd.DataFrame):
        return value.copy(deep=True)
    if isinstance(value, pd.Series):
        return plain(value.to_dict(), _parents)
    parents = set() if _parents is None else _parents
    if id(value) in parents:
        return None
    parents.add(id(value))
    try:
        if isinstance(value, Mapping):
            return {str(key): plain(item, parents) for key, item in value.items()
                    if key not in {"strategy", "candle_analysis_class", "for_api_json", "data", "data_remain"}}
        if isinstance(value, (tuple, list, set, frozenset)):
            return [plain(item, parents) for item in value]
        if is_dataclass(value) and not isinstance(value, type):
            return {field.name: plain(getattr(value, field.name), parents) for field in fields(value)}
        raise TypeError(f"upstream value requires an explicit mapping: {type(value).__name__}")
    finally:
        parents.remove(id(value))
