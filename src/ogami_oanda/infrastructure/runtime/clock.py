from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, tzinfo
from zoneinfo import ZoneInfo


@dataclass(frozen=True)
class SystemClock:
    timezone: tzinfo = ZoneInfo("Asia/Tokyo")

    def now(self) -> datetime:
        return datetime.now(self.timezone).replace(microsecond=0)
