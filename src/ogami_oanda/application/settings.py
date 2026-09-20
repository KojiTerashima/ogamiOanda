from __future__ import annotations

from dataclasses import dataclass, field
import math
from types import MappingProxyType
from typing import Mapping

from ogami_oanda.domain.market.currency_pair import currency_pair


def validate_spread_limit_pips(value: object) -> float:
    """Accept finite nonnegative numbers, never boolean/string coercions."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("spread_limit_pips must be a finite nonnegative number")
    try:
        result = float(value)
    except OverflowError:
        raise ValueError("spread_limit_pips must be a finite nonnegative number") from None
    if not math.isfinite(result) or result < 0:
        raise ValueError("spread_limit_pips must be a finite nonnegative number")
    return result


def resolve_spread_limit_pips(pair: str, value: float | None = None) -> float:
    """Resolve a per-run override without changing currency definitions."""
    default = currency_pair(pair).spread_limit_pips
    return default if value is None else validate_spread_limit_pips(value)


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
    spread_limit_pips: Mapping[str, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.spread_limit_pips, Mapping):
            raise ValueError("trading.spread_limit_pips must be a pair-to-number mapping")
        limits = {}
        for pair, value in self.spread_limit_pips.items():
            if pair not in ("USD_JPY", "EUR_USD", "AUD_USD"):
                raise ValueError("trading.spread_limit_pips contains an unsupported pair")
            limits[pair] = validate_spread_limit_pips(value)
        object.__setattr__(self, "spread_limit_pips", MappingProxyType(limits))

    def spread_limit_for(self, pair: str) -> float:
        return resolve_spread_limit_pips(pair, self.spread_limit_pips.get(pair))
