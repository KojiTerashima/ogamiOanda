"""Historical data acquisition and storage boundaries."""

from datetime import datetime
from typing import Iterable, Protocol

from ogami_oanda.domain.market.history import HistoricalCandle


class HistoricalSource(Protocol):
    def fetch(self, pair: str, start: datetime, end: datetime) -> list[HistoricalCandle]: ...


class HistoricalRepository(Protocol):
    pair: str

    def missing_intervals(self, start: datetime, end: datetime) -> list[tuple[datetime, datetime]]: ...

    def covers(self, start: datetime, end: datetime) -> bool: ...

    def validate(self, start: datetime, end: datetime) -> None: ...

    def write_interval(self, start: datetime, end: datetime, candles: Iterable[HistoricalCandle]) -> None: ...

    def read(self, start: datetime, end: datetime) -> Iterable[HistoricalCandle]: ...
