from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class CandleFrameSchema:
    pair: str
    granularity: str
    required_columns: tuple[str, ...] = ("time_jp", "open", "close", "high", "low")

    def validate(self, frame: pd.DataFrame) -> None:
        missing = [column for column in self.required_columns if column not in frame.columns]
        if missing:
            raise ValueError(f"Missing candle columns: {', '.join(missing)}")
        if frame.empty:
            raise ValueError("Candle frame must not be empty")
        timestamps = pd.to_datetime(frame["time_jp"], format="%Y/%m/%d %H:%M:%S", errors="raise")
        if not timestamps.is_monotonic_decreasing:
            raise ValueError("Candle frame must be ordered newest to oldest")
