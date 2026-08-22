from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class TradingSchedule:
    analysis_interval_min: int = 5
    analysis_start_second: int = 6
    analysis_end_second: int = 30
    minimum_analysis_elapsed_seconds: int = 60
    position_update_interval_seconds: int = 2

    def is_market_closed(self, now: datetime) -> bool:
        """The legacy loop does no work on Sunday."""
        return now.weekday() == 6

    def is_update_only_window(self, now: datetime) -> bool:
        """Weekend transition windows retain lifecycle updates but never analyze."""
        if now.weekday() == 5:
            return now.hour >= 4
        if now.weekday() == 0:
            # The historical runner kept Monday 07:xx in update-only mode and
            # resumed analysis from 08:00.
            return now.hour <= 7
        return False

    def should_run_analysis(self, now: datetime, elapsed_seconds: float, update_only: bool) -> bool:
        return (
            not update_only
            and now.minute % self.analysis_interval_min == 0
            and self.analysis_start_second <= now.second < self.analysis_end_second
            and elapsed_seconds > self.minimum_analysis_elapsed_seconds
        )

    def should_run_position_update(self, now: datetime) -> bool:
        return now.second % self.position_update_interval_seconds == 0
