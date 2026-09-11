"""Atomic daily gzip CSV snapshots with a resumable, integrity-checked manifest."""

from __future__ import annotations

from contextlib import contextmanager
import csv
import fcntl
from datetime import datetime, timedelta
import gzip
import hashlib
import io
import json
import math
import os
from pathlib import Path
import tempfile
from typing import Iterable, Iterator
from zoneinfo import ZoneInfo

from ogami_oanda.domain.market.currency_pair import currency_pair
from ogami_oanda.domain.market.history import HistoricalCandle, OHLC, utc_time

FIELDS = ["time", *[f"{component}_{key}" for component in ("mid", "bid", "ask")
                   for key in ("open", "high", "low", "close")], "volume", "complete"]


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def atomic_json(path: Path, value: object) -> None:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False).encode()
    atomic_bytes(path, payload)


def atomic_bytes(path: Path, value: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    name = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
            name = stream.name
            stream.write(value)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        if name is not None and os.path.exists(name):
            os.unlink(name)


def candle_row(candle: HistoricalCandle) -> dict:
    return {"time": candle.time.isoformat(), "volume": candle.volume, "complete": True,
            **{f"{component}_{key}": getattr(getattr(candle, component), key)
               for component in ("mid", "bid", "ask") for key in ("open", "high", "low", "close")}}


def row_candle(row: dict) -> HistoricalCandle:
    try:
        prices = [OHLC(*(float(row[f"{component}_{key}"]) for key in ("open", "high", "low", "close")))
                  for component in ("mid", "bid", "ask")]
        return HistoricalCandle(utc_time(row["time"]), *prices, volume=int(row["volume"]),
                                complete=str(row["complete"]).lower() == "true")
    except (KeyError, TypeError, ValueError, AttributeError, OverflowError):
        raise ValueError("malformed historical candle row") from None


def _range(start: datetime, end: datetime) -> tuple[datetime, datetime]:
    start, end = utc_time(start), utc_time(end)
    if start >= end:
        raise ValueError("historical range must be increasing")
    return start, end


class HistoricalStore:
    def __init__(self, root: str | Path, pair: str) -> None:
        currency_pair(pair)
        self.root = Path(root)
        self.pair = pair
        self.manifest_path = self.root / "manifest.json"
        self._reload_manifest()

    def _reload_manifest(self) -> None:
        self.manifest = {"schema_version": 1, "pair": self.pair, "price_mode": "MBA", "intervals": [], "files": {}}
        if self.manifest_path.exists():
            try:
                self.manifest = json.loads(self.manifest_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, UnicodeError):
                raise ValueError("malformed historical manifest") from None
            if not isinstance(self.manifest, dict):
                raise ValueError("historical manifest must be an object")
            if self.manifest.get("schema_version") != 1 or self.manifest.get("pair") != self.pair:
                raise ValueError("historical manifest version or pair mismatch")
        if self.manifest.get("price_mode") != "MBA" or not isinstance(self.manifest.get("files"), dict):
            raise ValueError("historical manifest schema mismatch")
        self._intervals()

    @contextmanager
    def download_lock(self) -> Iterator["HistoricalStore"]:
        """Exclude concurrent download writers; process exit releases the lock."""
        self.root.mkdir(parents=True, exist_ok=True)
        with (self.root / ".download.lock").open("a+b") as stream:
            try:
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise ValueError("historical download already has an active writer") from None
            try:
                # Another writer may have committed since this object's
                # construction. Read its final snapshot only after exclusion.
                self._reload_manifest()
                yield self
            finally:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)

    def _file(self, entry: dict) -> Path:
        if not isinstance(entry, dict) or not isinstance(entry.get("path"), str):
            raise ValueError("invalid historical manifest file entry")
        name = entry["path"]
        if Path(name).name != name:
            raise ValueError("historical manifest path must be a basename")
        path = self.root / name
        if path.resolve().parent != self.root.resolve():
            raise ValueError("historical data path escapes dataset")
        return path

    def _intervals(self) -> list[tuple[datetime, datetime, int]]:
        try:
            intervals = self.manifest["intervals"]
            if not isinstance(intervals, list):
                raise ValueError
            result = []
            for interval in intervals:
                left, right = _range(utc_time(interval["from"]), utc_time(interval["to"]))
                count = interval["count"]
                if (right - left) > timedelta(hours=6) or left.date() != (right - timedelta(microseconds=1)).date():
                    raise ValueError
                if type(count) is not int or count < 0 or count > 4320:
                    raise ValueError
                result.append((left, right, count))
            result.sort()
            if any(left[1] > right[0] for left, right in zip(result, result[1:])):
                raise ValueError
            return result
        except (KeyError, TypeError, ValueError, AttributeError):
            raise ValueError("invalid historical acquisition intervals") from None

    def missing_intervals(self, start: datetime, end: datetime) -> list[tuple[datetime, datetime]]:
        start, end = _range(start, end)
        cursor = start
        missing = []
        for left, right, _ in self._intervals():
            if right <= cursor:
                continue
            if left >= end:
                break
            if left > cursor:
                missing.append((cursor, left))
            cursor = max(cursor, right)
            if cursor >= end:
                break
        if cursor < end:
            missing.append((cursor, end))
        return missing

    def covers(self, start: datetime, end: datetime) -> bool:
        return not self.missing_intervals(start, end)

    def _day_rows(self, day: str, entry: dict) -> Iterator[HistoricalCandle]:
        path = self._file(entry)
        if not path.is_file() or file_hash(path) != entry.get("sha256"):
            raise ValueError("historical file hash mismatch")
        expected = entry.get("rows")
        if type(expected) is not int or expected < 0 or expected > 17280:
            raise ValueError("historical file row count mismatch")
        count = 0
        previous = None
        try:
            with gzip.open(path, "rt", encoding="utf-8", newline="") as stream:
                reader = csv.DictReader(stream)
                if reader.fieldnames != FIELDS:
                    raise ValueError("historical candle columns mismatch")
                for row in reader:
                    if None in row:
                        raise ValueError("malformed historical candle row")
                    bar = row_candle(row)
                    if bar.time.date().isoformat() != day:
                        raise ValueError("historical candle outside daily file")
                    if previous is not None and bar.time <= previous:
                        raise ValueError("historical candles must be in strictly increasing order")
                    previous = bar.time
                    count += 1
                    if count > expected:
                        raise ValueError("historical file row count mismatch")
                    yield bar
        except (OSError, EOFError, UnicodeError, csv.Error):
            raise ValueError("malformed historical candle file") from None
        if count != expected:
            raise ValueError("historical file row count mismatch")

    def _validated_day(self, day: str, entry: dict, intervals) -> Iterator[HistoricalCandle]:
        acquired = [(left, right, count) for left, right, count in intervals if left.date().isoformat() == day]
        counts = [0] * len(acquired)
        index = 0
        for bar in self._day_rows(day, entry):
            while index < len(acquired) and bar.time >= acquired[index][1]:
                index += 1
            if index >= len(acquired) or bar.time < acquired[index][0]:
                raise ValueError("historical candle outside acquisition intervals")
            counts[index] += 1
            yield bar
        if counts != [count for _, _, count in acquired]:
            raise ValueError("historical acquisition row count mismatch")

    def validate(self, start: datetime, end: datetime) -> None:
        start, end = _range(start, end)
        if not self.covers(start, end):
            raise ValueError("historical acquisition is incomplete for requested interval")
        intervals = self._intervals()
        last_day = (end - timedelta(microseconds=1)).date().isoformat()
        first_day = start.date().isoformat()
        expected_days = {left.date().isoformat() for left, right, _ in intervals
                         if left < end and right > start}
        if expected_days - self.manifest["files"].keys():
            raise ValueError("historical acquisition is missing a daily file")
        for day, entry in sorted(self.manifest["files"].items()):
            if first_day <= day <= last_day:
                # Exhaust the complete daily stream, including rows outside the
                # requested subrange; never materialize a full-history list.
                for _ in self._validated_day(day, entry, intervals):
                    pass

    def write_interval(self, start: datetime, end: datetime, candles: Iterable[HistoricalCandle]) -> None:
        start, end = _range(start, end)
        if start >= end or (end - start) > timedelta(hours=6):
            raise ValueError("storage interval must be positive and at most six hours")
        if start.date() != (end - timedelta(microseconds=1)).date():
            raise ValueError("storage interval must stay within a UTC day")
        intervals = self._intervals()
        if any(start < right and end > left for left, right, _ in intervals):
            raise ValueError("historical interval overlaps an acquired interval")
        new = []
        previous = None
        for bar in candles:
            if not isinstance(bar, HistoricalCandle) or len(new) >= 4320:
                raise ValueError("invalid historical candle interval")
            if not start <= bar.time < end:
                raise ValueError("historical candle outside storage interval")
            if previous is not None and bar.time <= previous:
                raise ValueError("historical candles must be in strictly increasing order")
            previous = bar.time
            new.append(bar)
        day = start.date().isoformat()
        old = self.manifest["files"].get(day)
        existing = []
        if old is not None:
            existing = list(self._validated_day(day, old, intervals))
        merged = sorted([*existing, *new], key=lambda bar: bar.time)
        if any(a.time >= b.time for a, b in zip(merged, merged[1:])):
            raise ValueError("historical candles must be in strictly increasing order")
        text = io.StringIO(newline="")
        writer = csv.DictWriter(text, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(candle_row(bar) for bar in merged)
        compressed = gzip.compress(text.getvalue().encode(), mtime=0)
        digest = hashlib.sha256(compressed).hexdigest()
        filename = f"{day}-{digest[:16]}.csv.gz"
        atomic_bytes(self.root / filename, compressed)
        manifest = {**self.manifest, "files": {**self.manifest["files"], day: {
            "path": filename, "sha256": digest, "rows": len(merged)}},
            "intervals": [*self.manifest["intervals"], {"from": start.isoformat(), "to": end.isoformat(), "count": len(new)}]}
        # Immutable data file precedes the manifest commit: interruption cannot
        # invalidate the previous manifest's snapshot.
        atomic_json(self.manifest_path, manifest)
        self.manifest = manifest
        # Retain immutable prior snapshots: an already running reader may
        # still hold their manifest. Cleanup requires separate reader coordination.

    def read(self, start: datetime, end: datetime) -> Iterator[HistoricalCandle]:
        start, end = _range(start, end)
        last_day = (end - timedelta(microseconds=1)).date().isoformat()
        intervals = self._intervals()
        for day, entry in sorted(self.manifest["files"].items()):
            if start.date().isoformat() <= day <= last_day:
                for bar in self._validated_day(day, entry, intervals):
                    if start <= bar.time < end:
                        yield bar


def read_mid_csv(path: str | Path, pair: str, spread_pips: float | None) -> Iterator[HistoricalCandle]:
    if spread_pips is None or not math.isfinite(spread_pips) or spread_pips < 0:
        raise ValueError("Mid CSV requires an explicit nonnegative fixed spread")
    half = spread_pips * currency_pair(pair).pip_value / 2
    path = Path(path)
    opener = gzip.open if path.suffix == ".gz" else open
    previous = None
    with opener(path, "rt", encoding="utf-8-sig", newline="") as stream:
        for row in csv.DictReader(stream):
            if row.get("time"):
                at = utc_time(row["time"])
            else:
                at = datetime.strptime(row["time_jp"], "%Y/%m/%d %H:%M:%S").replace(tzinfo=ZoneInfo("Asia/Tokyo"))
            values = [float(row[key]) for key in ("open", "high", "low", "close")]
            bar = HistoricalCandle(at, OHLC(*values), OHLC(*(v - half for v in values)),
                                   OHLC(*(v + half for v in values)), volume=int(row.get("volume", 0)),
                                   complete=row.get("complete", "true").lower() == "true")
            if previous is not None and bar.time <= previous:
                raise ValueError("Mid CSV must be in strictly increasing order")
            previous = bar.time
            yield bar
