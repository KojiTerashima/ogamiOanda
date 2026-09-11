"""Validated, immutable five-second historical prices (UTC candle starts)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import math

GRANULARITY_SECONDS = {"S5": 5, "M1": 60, "M5": 300, "M30": 1800, "H1": 3600}


@dataclass(frozen=True, slots=True)
class OHLC:
    open: float
    high: float
    low: float
    close: float

    def __post_init__(self) -> None:
        values = (self.open, self.high, self.low, self.close)
        if not all(math.isfinite(v) and v > 0 for v in values):
            raise ValueError("OHLC prices must be finite and positive")
        if not self.low <= min(self.open, self.close) <= max(self.open, self.close) <= self.high:
            raise ValueError("invalid OHLC range")


@dataclass(frozen=True, slots=True)
class HistoricalCandle:
    time: datetime
    mid: OHLC
    bid: OHLC
    ask: OHLC
    volume: int = 0
    complete: bool = True

    def __post_init__(self) -> None:
        if self.time.tzinfo is None or self.time.utcoffset() is None:
            raise ValueError("candle time requires an explicit timezone")
        utc = self.time.astimezone(timezone.utc)
        if utc.microsecond or utc.second % 5:
            raise ValueError("candle time must align to S5")
        object.__setattr__(self, "time", utc)
        if type(self.volume) is not int or self.volume < 0 or self.complete is not True:
            raise ValueError("historical candles must be complete with nonnegative integer volume")
        for field in ("open", "high", "low", "close"):
            if not getattr(self.bid, field) <= getattr(self.mid, field) <= getattr(self.ask, field):
                raise ValueError("Bid/Mid/Ask prices are inconsistent")

    @property
    def end(self) -> datetime:
        return self.time + timedelta(seconds=5)


def utc_time(value: str | datetime) -> datetime:
    result = datetime.fromisoformat(value.replace("Z", "+00:00")) if isinstance(value, str) else value
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError("timestamps require Z or an explicit UTC offset")
    return result.astimezone(timezone.utc)
