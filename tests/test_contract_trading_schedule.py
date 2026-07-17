from datetime import datetime

import pytest

from ogami_oanda.application.scheduling import TradingSchedule


@pytest.mark.contract
def test_schedule_runs_analysis_only_in_legacy_five_minute_window():
    schedule = TradingSchedule()
    eligible = datetime(2026, 1, 2, 3, 5, 6)

    assert schedule.should_run_analysis(eligible, elapsed_seconds=61, update_only=False) is True
    assert schedule.should_run_analysis(eligible.replace(second=5), elapsed_seconds=61, update_only=False) is False
    assert schedule.should_run_analysis(eligible.replace(second=30), elapsed_seconds=61, update_only=False) is False
    assert schedule.should_run_analysis(eligible.replace(minute=6), elapsed_seconds=61, update_only=False) is False
    assert schedule.should_run_analysis(eligible, elapsed_seconds=60, update_only=False) is False
    assert schedule.should_run_analysis(eligible, elapsed_seconds=61, update_only=True) is False


@pytest.mark.contract
def test_schedule_runs_position_update_on_even_seconds():
    schedule = TradingSchedule()

    assert schedule.should_run_position_update(datetime(2026, 1, 2, 3, 4, 2)) is True
    assert schedule.should_run_position_update(datetime(2026, 1, 2, 3, 4, 3)) is False
