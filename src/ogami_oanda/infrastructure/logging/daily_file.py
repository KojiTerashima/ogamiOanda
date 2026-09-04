from __future__ import annotations

import gzip
import os
import sys
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import TextIO
from zoneinfo import ZoneInfo

JST = ZoneInfo("Asia/Tokyo")
DEFAULT_PREFIX = "ogami-oanda"


class DailyFileTee:
    def __init__(
        self,
        stream: TextIO,
        log_dir: str | Path,
        *,
        prefix: str = DEFAULT_PREFIX,
        now: Callable[[], datetime] | None = None,
        compress_older_than_days: int | None = None,
    ) -> None:
        self.stream = stream
        self.log_dir = Path(log_dir)
        self.prefix = prefix
        self.now = now or (lambda: datetime.now(JST))
        self.compress_older_than_days = compress_older_than_days
        self._current_date: str | None = None
        self._last_compressed_date: str | None = None
        self._log_file: TextIO | None = None

    def write(self, text: str) -> int:
        written = self.stream.write(text)
        log_file = self._open_log_file()
        log_file.write(text)
        return written

    def flush(self) -> None:
        self.stream.flush()
        if self._log_file is not None:
            self._log_file.flush()

    def close_log_file(self) -> None:
        if self._log_file is None:
            return
        self._log_file.close()
        self._log_file = None
        self._current_date = None

    def isatty(self) -> bool:
        return self.stream.isatty()

    def fileno(self) -> int:
        return self.stream.fileno()

    @property
    def encoding(self) -> str | None:
        return self.stream.encoding

    @property
    def errors(self) -> str | None:
        return self.stream.errors

    def __getattr__(self, name: str):
        return getattr(self.stream, name)

    def _open_log_file(self) -> TextIO:
        current_time = _current_jst_datetime(self.now())
        current_date = current_time.date().isoformat()
        if self._log_file is not None and self._current_date == current_date:
            return self._log_file
        self.close_log_file()
        self.log_dir.mkdir(parents=True, exist_ok=True)
        path = self.log_dir / f"{self.prefix}-{current_date}.log"
        self._log_file = path.open("a", encoding="utf-8")
        self._current_date = current_date
        if (
            self.compress_older_than_days is not None
            and self._last_compressed_date != current_date
        ):
            self._last_compressed_date = current_date
            compress_old_daily_logs(
                self.log_dir,
                now=lambda: current_time,
                older_than_days=self.compress_older_than_days,
                prefix=self.prefix,
            )
        return self._log_file


def setup_daily_file_logging(
    log_dir: str | Path,
    *,
    now: Callable[[], datetime] | None = None,
    compress_older_than_days: int = 10,
) -> None:
    compress_old_daily_logs(
        log_dir,
        now=now,
        older_than_days=compress_older_than_days,
    )
    if not isinstance(sys.stdout, DailyFileTee):
        sys.stdout = DailyFileTee(
            sys.stdout,
            log_dir,
            now=now,
            compress_older_than_days=compress_older_than_days,
        )
    if not isinstance(sys.stderr, DailyFileTee):
        sys.stderr = DailyFileTee(
            sys.stderr,
            log_dir,
            now=now,
            compress_older_than_days=compress_older_than_days,
        )


def compress_old_daily_logs(
    log_dir: str | Path,
    *,
    now: Callable[[], datetime] | None = None,
    older_than_days: int = 10,
    prefix: str = DEFAULT_PREFIX,
) -> tuple[Path, ...]:
    directory = Path(log_dir)
    if not directory.exists():
        return ()
    current_time = (now or (lambda: datetime.now(JST)))()
    today = _current_jst_datetime(current_time).date()
    compressed: list[Path] = []
    for log_path in sorted(directory.glob(f"{prefix}-*.log")):
        log_date = _date_from_log_path(log_path, prefix)
        if log_date is None or (today - log_date).days <= older_than_days:
            continue
        compressed_path = log_path.with_suffix(log_path.suffix + ".gz")
        if compressed_path.exists():
            continue
        if _gzip_log_file(log_path, compressed_path):
            compressed.append(compressed_path)
    return tuple(compressed)


def _current_jst_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=JST)
    return value.astimezone(JST)


def _date_from_log_path(log_path: Path, prefix: str):
    date_text = log_path.name.removeprefix(f"{prefix}-").removesuffix(".log")
    try:
        return datetime.strptime(date_text, "%Y-%m-%d").date()
    except ValueError:
        return None


def _gzip_log_file(log_path: Path, compressed_path: Path) -> bool:
    staging_path = log_path.with_name(log_path.name + ".compressing")
    temporary_compressed_path = compressed_path.with_name(compressed_path.name + ".tmp")
    try:
        os.replace(log_path, staging_path)
    except OSError:
        return False
    try:
        with staging_path.open("rb") as source_file:
            with gzip.open(temporary_compressed_path, "wb") as compressed_file:
                compressed_file.writelines(source_file)
        os.replace(temporary_compressed_path, compressed_path)
        staging_path.unlink()
        return True
    except OSError:
        if temporary_compressed_path.exists():
            temporary_compressed_path.unlink()
        if staging_path.exists() and not log_path.exists():
            os.replace(staging_path, log_path)
        return False
