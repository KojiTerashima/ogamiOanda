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

    def should_run_analysis(self, now: datetime, elapsed_seconds: float, update_only: bool) -> bool:
        return (
            not update_only
            and now.minute % self.analysis_interval_min == 0
            and self.analysis_start_second <= now.second < self.analysis_end_second
            and elapsed_seconds > self.minimum_analysis_elapsed_seconds
        )

    def should_run_position_update(self, now: datetime) -> bool:
        return now.second % self.position_update_interval_seconds == 0
