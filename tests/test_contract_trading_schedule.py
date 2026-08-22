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


@pytest.mark.contract
@pytest.mark.parametrize(
    ("now", "market_closed", "update_only"),
    [
        (datetime(2026, 1, 4, 0, 0, 0), True, False),  # Sunday
        (datetime(2026, 1, 3, 3, 59, 59), False, False),  # Saturday
        (datetime(2026, 1, 3, 4, 0, 0), False, True),
        (datetime(2026, 1, 5, 7, 59, 59), False, True),  # Monday
        (datetime(2026, 1, 5, 8, 0, 0), False, False),
    ],
)
def test_schedule_preserves_legacy_weekend_boundaries(now, market_closed, update_only):
    schedule = TradingSchedule()

    assert schedule.is_market_closed(now) is market_closed
    assert schedule.is_update_only_window(now) is update_only
