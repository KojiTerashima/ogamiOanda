"""An independent, causal S5 aggregation oracle for the bounded comparison period."""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

import numpy as np
import pandas as pd

from ogami_oanda.adapters.repositories.historical_store import HistoricalStore
from ogami_oanda.domain.market.history import HistoricalCandle, OHLC

from .common import digest


SECONDS = {"S5": 5, "M5": 300, "M30": 1800, "H1": 3600}
RAW_COLUMNS = [f"{side}_{key}" for side in ("mid", "bid", "ask") for key in ("open", "high", "low", "close")]


def fixed_spread(candle, pair, spread=0.8):
    half = spread * (0.01 if pair == "USD_JPY" else 0.0001) / 2
    values = [getattr(candle.mid, key) for key in ("open", "high", "low", "close")]
    return replace(candle, bid=OHLC(*(v - half for v in values)), ask=OHLC(*(v + half for v in values)))


def frame_columns(frame):
    frame = frame.copy()
    frame["time"] = frame.index.map(lambda t: t.isoformat())
    frame["time_jp_dt"] = frame.index.tz_convert("Asia/Tokyo").tz_localize(None)
    frame["time_jp"] = frame["time_jp_dt"].dt.strftime("%Y/%m/%d %H:%M:%S")
    return frame.reset_index(drop=True)


class Dataset:
    def __init__(self, pair, candles):
        self.pair = pair
        rows = []
        for candle in candles:
            rows.append((candle.time, *[getattr(getattr(candle, side), key)
                                       for side in ("mid", "bid", "ask") for key in ("open", "high", "low", "close")], candle.volume))
        if not rows:
            raise ValueError("no stored S5 observations")
        self.raw = pd.DataFrame(rows, columns=["time", *RAW_COLUMNS, "volume"]).set_index("time")
        self.raw.index = pd.DatetimeIndex(self.raw.index).as_unit("ns")
        if not self.raw.index.is_monotonic_increasing or self.raw.index.has_duplicates:
            raise ValueError("S5 observations must be unique and increasing")
        self.times = self.raw.index.asi8
        self.values = self.raw.to_numpy()
        self.mid = self.raw[[f"mid_{k}" for k in ("open", "high", "low", "close")]+["volume"]].rename(columns=lambda k: k.removeprefix("mid_"))
        self.grouped = {}
        for timeframe, seconds in SECONDS.items():
            buckets = self.mid.index.floor(f"{seconds}s")
            self.grouped[timeframe] = self.mid.groupby(buckets).agg(
                {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"})

    @classmethod
    def from_store(cls, root, pair, start, end):
        store = HistoricalStore(root, pair)
        if not store.covers(start, end):
            raise ValueError("stored acquisition does not cover comparison plus warmup")
        # read validates hashes, ordering, OHLC and interval counts while exhausting each day.
        dataset = cls(pair, store.read(start, end))
        dataset.manifest = store.manifest
        dataset.manifest_sha256 = digest(store.manifest)
        return dataset

    def bounds(self, start, end):
        return (int(np.searchsorted(self.times, pd.Timestamp(start).value)),
                int(np.searchsorted(self.times, pd.Timestamp(end).value)))

    def candle(self, index, fixed=False):
        values = self.values[index]
        candle = HistoricalCandle(self.raw.index[index].to_pydatetime(), OHLC(*values[:4]),
                                  OHLC(*values[4:8]), OHLC(*values[8:12]), volume=int(values[12]))
        return fixed_spread(candle, self.pair) if fixed else candle

    def candles(self, start, end, fixed=False):
        left, right = self.bounds(start, end)
        for index in range(left, right):
            yield self.candle(index, fixed)

    def observed_index(self, at):
        # A candle timestamp denotes its START; its close is available five seconds later.
        return int(np.searchsorted(self.times, (pd.Timestamp(at) - pd.Timedelta(seconds=5)).value, side="right")) - 1

    def frames(self, at, counts=None):
        counts = counts or dict.fromkeys(SECONDS, 250)
        index = self.observed_index(at)
        if index < 0:
            raise ValueError("no observed S5 before evaluation")
        last_start = self.raw.index[index]
        last_end = last_start + pd.Timedelta(seconds=5)
        close = float(self.values[index][3])
        result = {}
        for timeframe, count in counts.items():
            seconds = SECONDS[timeframe]
            bucket = last_start.floor(f"{seconds}s")
            prior = self.grouped[timeframe].loc[self.grouped[timeframe].index < bucket].tail(count)
            partial = self.mid.iloc[self.bounds(bucket, last_end)[0]:index+1]
            current = pd.DataFrame({"open": [partial.open.iloc[0]], "high": [partial.high.max()],
                                    "low": [partial.low.min()], "close": [close], "volume": [partial.volume.sum()]},
                                   index=pd.DatetimeIndex([bucket]))
            frame = pd.concat([prior, current])
            frame["complete"] = True
            if last_end.value % (seconds * 1_000_000_000) == 0:
                placeholder = pd.DataFrame({"open": [close], "high": [close], "low": [close], "close": [close],
                                            "volume": [0], "complete": [False]}, index=pd.DatetimeIndex([last_end]))
                frame = pd.concat([frame, placeholder])
            else:
                frame.iloc[-1, frame.columns.get_loc("complete")] = False
            result[timeframe] = frame_columns(frame.tail(count)).iloc[::-1].reset_index(drop=True)
        return result, close, last_end

    def inspection_frame(self, start, end):
        left, right = self.bounds(start, end)
        return frame_columns(self.mid.iloc[left:right])

    def quality(self, start, end):
        left, right = self.bounds(start, end)
        times = self.raw.index[left:right]
        edges = [(pd.Timestamp(start), times[0])] if len(times) else [(pd.Timestamp(start), pd.Timestamp(end))]
        if len(times):
            edges.extend((a + pd.Timedelta(seconds=5), b) for a, b in zip(times[:-1], times[1:])
                         if b - a > pd.Timedelta(seconds=5))
            edges.append((times[-1] + pd.Timedelta(seconds=5), pd.Timestamp(end)))
        gaps = [{"from": a.isoformat(), "to": b.isoformat(), "seconds": (b-a).total_seconds()} for a,b in edges if b>a]
        return {"observations": right-left, "gaps": gaps, "gap_seconds": sum(g["seconds"] for g in gaps),
                "synthetic_candles": 0, "warmup_from": (pd.Timestamp(start)-timedelta(days=28)).isoformat()}
