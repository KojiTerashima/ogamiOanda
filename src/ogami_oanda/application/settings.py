from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TradingSettings:
    """Business limits consumed by trading application services."""

    default_pair: str = "USD_JPY"
    line_units: float = 1.0
    risk_yen: float = 500.0
    max_positions: int = 15
    normal_slot_count: int = 6
    mid_slot_count: int = 8
    high_slot_count: int = 1
    mid_priority_threshold: int = 10
    high_priority_threshold: int = 100
