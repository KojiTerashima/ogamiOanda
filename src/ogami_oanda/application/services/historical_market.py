"""Bounded market windows built only from prices already replayed."""

from __future__ import annotations

from collections import deque
from datetime import datetime, timezone
from typing import Callable
from zoneinfo import ZoneInfo

import pandas as pd

from ogami_oanda.application.ports.market_data import MarketQuote
from ogami_oanda.domain.market.currency_pair import currency_pair
from ogami_oanda.domain.market.history import GRANULARITY_SECONDS, HistoricalCandle

JST = ZoneInfo("Asia/Tokyo")


class ReplayClock:
    def __init__(self, value: datetime) -> None:
        self.set(value)

    def set(self, value: datetime) -> None:
        if value.tzinfo is None:
            raise ValueError("replay clock requires timezone-aware time")
        self.value = value.astimezone(JST)

    def now(self) -> datetime:
        return self.value


class HistoricalMarket:
    def __init__(self, pair: str, requirements: dict[str, int], *,
                 gap_sink: Callable[[datetime, datetime], None] | None = None) -> None:
        currency_pair(pair)
        if any(k not in GRANULARITY_SECONDS or type(v) is not int or v < 1 for k, v in requirements.items()):
            raise ValueError("invalid historical market requirements")
        self.pair = pair
        self.requirements = dict(requirements)
        self._frames: dict[str, deque] = {key: deque(maxlen=count) for key, count in requirements.items()}
        self._tables: dict[str, pd.DataFrame] = {}
        self._columns: dict[str, dict] = {}
        self._table_starts: dict[str, datetime] = {}
        self.last: HistoricalCandle | None = None
        self.gap_count = 0
        self.gap_seconds = 0.0
        self.gap_sink = gap_sink

    def advance(self, candle: HistoricalCandle) -> None:
        if self.last is not None:
            if candle.time <= self.last.time:
                raise ValueError("historical candles must be in strictly increasing order")
            gap = (candle.time - self.last.end).total_seconds()
            if gap > 0:
                self.record_gap(self.last.end, candle.time)
        self.last = candle
        for granularity, records in self._frames.items():
            seconds = GRANULARITY_SECONDS[granularity]
            start = datetime.fromtimestamp(int(candle.time.timestamp()) // seconds * seconds, timezone.utc)
            if records and records[-1]["_start"] != start:
                # A placeholder created at the previous boundary is not a traded
                # candle. Drop it across a gap rather than fabricating activity.
                if records[-1]["_observed"] is False:
                    records.pop()
                elif records:
                    records[-1]["complete"] = True
            if not records or records[-1]["_start"] != start:
                records.append(self._record(start, candle.mid.open))
            row = records[-1]
            if not row["_observed"]:
                row.update(open=candle.mid.open, high=candle.mid.high, low=candle.mid.low)
            row["high"] = max(row["high"], candle.mid.high)
            row["low"] = min(row["low"], candle.mid.low)
            row["close"] = candle.mid.close
            row["volume"] += candle.volume
            row["_observed"] = True
            boundary = int(candle.end.timestamp()) % seconds == 0
            if boundary:
                row["complete"] = True
                # Current forming candle contains only the last observed quote.
                records.append(self._record(candle.end, candle.mid.close))

    def record_gap(self, start: datetime, end: datetime) -> None:
        self.gap_count += 1
        self.gap_seconds += (end - start).total_seconds()
        if self.gap_sink is not None:
            self.gap_sink(start, end)

    @staticmethod
    def _record(start: datetime, price: float) -> dict:
        return {"_start": start, "_observed": False, "time": start.isoformat(),
                "time_jp": start.astimezone(JST).strftime("%Y/%m/%d %H:%M:%S"),
                "time_jp_dt": start.astimezone(JST).replace(tzinfo=None),
                "open": price, "high": price, "low": price, "close": price,
                "volume": 0, "complete": False}

    @property
    def ready(self) -> bool:
        return self.last is not None and all(len(self._frames[key]) >= count for key, count in self.requirements.items())

    @property
    def buffered_candles(self) -> int:
        return sum(len(rows) for rows in self._frames.values())

    def candles(self, pair: str, granularity: str, count: int) -> pd.DataFrame:
        if pair != self.pair or granularity not in self._frames:
            raise ValueError("candle request is outside declared requirements")
        if count > self.requirements[granularity]:
            raise ValueError("candle request exceeds declared window")
        records = self._frames[granularity]
        table = self._tables.get(granularity)
        previous_start = self._table_starts.get(granularity)
        same_row = bool(records) and records[-1]["_start"] == previous_start
        shifted = len(records) > 1 and records[-2]["_start"] == previous_start
        if table is None or len(table) != len(records) or not (same_row or shifted):
            table = pd.DataFrame([
                {key: value for key, value in row.items() if not key.startswith("_")}
                for row in reversed(records)
            ])
            if records:
                table = table.astype({"time": object, "time_jp": object,
                                      **{key: float for key in ("open", "high", "low", "close")}}).copy()
            self._tables[granularity] = table
            self._columns[granularity] = {key: table[key].to_numpy(copy=False) for key in table.columns}
            for values in self._columns[granularity].values():
                # These arrays belong exclusively to the private cache; pandas
                # 3 exposes read-only views even when there are no shared users.
                values.setflags(write=True)
        else:
            # The private table owns these arrays. Public snapshots below are
            # copied, so neither future prices nor plugin edits can leak across
            # evaluations. Only the forming row and newly closed row change.
            for key, values in self._columns[granularity].items():
                if not same_row:
                    values[1:] = values[:-1]
                    values[1] = records[-2][key]
                values[0] = records[-1][key]
        if records:
            self._table_starts[granularity] = records[-1]["_start"]
        return table.copy() if count >= len(table) else table.iloc[:count].copy()

    def current_quote(self, pair: str) -> MarketQuote:
        if pair != self.pair or self.last is None:
            raise ValueError("no historical quote for pair")
        return MarketQuote(pair, self.last.bid.close, self.last.ask.close, self.last.mid.close,
                           source_time=self.last.end)

    def current_price(self, pair: str) -> float:
        return self.current_quote(pair).mid
