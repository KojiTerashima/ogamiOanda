from __future__ import annotations

import gzip
from datetime import datetime
from io import StringIO
from zoneinfo import ZoneInfo

from ogami_oanda.infrastructure.logging.daily_file import (
    DailyFileTee,
    compress_old_daily_logs,
)


def test_daily_file_tee_keeps_console_output_and_rotates_on_jst_date(tmp_path):
    moments = iter(
        [
            datetime(2026, 9, 3, 23, 59, tzinfo=ZoneInfo("Asia/Tokyo")),
            datetime(2026, 9, 4, 0, 0, tzinfo=ZoneInfo("Asia/Tokyo")),
        ]
    )
    console = StringIO()
    tee = DailyFileTee(console, tmp_path, now=lambda: next(moments))

    tee.write("before midnight\n")
    tee.write("after midnight\n")
    tee.flush()
    tee.close_log_file()

    assert console.getvalue() == "before midnight\nafter midnight\n"
    assert (tmp_path / "ogami-oanda-2026-09-03.log").read_text(
        encoding="utf-8"
    ) == "before midnight\n"
    assert (tmp_path / "ogami-oanda-2026-09-04.log").read_text(
        encoding="utf-8"
    ) == "after midnight\n"


def test_compress_old_daily_logs_gzips_only_logs_older_than_ten_days(tmp_path):
    old_log = tmp_path / "ogami-oanda-2026-08-24.log"
    boundary_log = tmp_path / "ogami-oanda-2026-08-25.log"
    today_log = tmp_path / "ogami-oanda-2026-09-04.log"
    old_log.write_text("old\n", encoding="utf-8")
    boundary_log.write_text("boundary\n", encoding="utf-8")
    today_log.write_text("today\n", encoding="utf-8")

    compressed = compress_old_daily_logs(
        tmp_path,
        now=lambda: datetime(2026, 9, 4, 12, 0, tzinfo=ZoneInfo("Asia/Tokyo")),
        older_than_days=10,
    )

    assert compressed == (tmp_path / "ogami-oanda-2026-08-24.log.gz",)
    assert not old_log.exists()
    with gzip.open(tmp_path / "ogami-oanda-2026-08-24.log.gz", "rt", encoding="utf-8") as log_file:
        assert log_file.read() == "old\n"
    assert boundary_log.read_text(encoding="utf-8") == "boundary\n"
    assert today_log.read_text(encoding="utf-8") == "today\n"


def test_daily_file_tee_compresses_old_logs_when_opening_a_new_day(tmp_path):
    old_log = tmp_path / "ogami-oanda-2026-08-24.log"
    old_log.write_text("old\n", encoding="utf-8")
    tee = DailyFileTee(
        StringIO(),
        tmp_path,
        now=lambda: datetime(2026, 9, 4, 0, 0, tzinfo=ZoneInfo("Asia/Tokyo")),
        compress_older_than_days=10,
    )

    tee.write("new day\n")
    tee.close_log_file()

    assert not old_log.exists()
    with gzip.open(tmp_path / "ogami-oanda-2026-08-24.log.gz", "rt", encoding="utf-8") as log_file:
        assert log_file.read() == "old\n"
    assert (tmp_path / "ogami-oanda-2026-09-04.log").read_text(
        encoding="utf-8"
    ) == "new day\n"
