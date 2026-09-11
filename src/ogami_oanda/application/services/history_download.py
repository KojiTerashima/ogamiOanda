"""Resumable bounded historical requests; credentials and files stay in adapters."""

from datetime import datetime, timedelta
from typing import Callable

from ogami_oanda.application.errors import TransientExternalServiceError
from ogami_oanda.application.ports.historical_data import HistoricalRepository, HistoricalSource
from ogami_oanda.domain.market.history import utc_time


def download_history(
    source: HistoricalSource,
    store: HistoricalRepository,
    start: datetime,
    end: datetime,
    *,
    sleep: Callable[[float], None],
    progress: Callable[[datetime], None] | None = None,
) -> None:
    start, end = utc_time(start), utc_time(end)
    if start >= end:
        raise ValueError("history range must be timezone-aware and increasing")
    missing = store.missing_intervals(start, end)
    # Validate already acquired spans before issuing any new network request.
    cursor = start
    for left, right in missing:
        if cursor < left:
            store.validate(cursor, left)
        cursor = right
    if cursor < end:
        store.validate(cursor, end)
    for left, right in missing:
        cursor = left
        while cursor < right:
            midnight = cursor.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
            stop = min(cursor + timedelta(hours=6), midnight, right)
            for attempt in range(4):
                try:
                    candles = source.fetch(store.pair, cursor, stop)
                    break
                except TransientExternalServiceError as error:
                    if attempt == 3:
                        raise
                    sleep(min(60, max(2 ** attempt, error.retry_after_seconds or 0)))
            store.write_interval(cursor, stop, candles)
            cursor = stop
            if progress is not None:
                progress(cursor)
    if not missing and progress is not None:
        progress(end)
