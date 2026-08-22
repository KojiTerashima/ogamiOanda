from datetime import timedelta

import pytest

from ogami_oanda.infrastructure.runtime import SystemClock


@pytest.mark.contract
def test_system_clock_uses_explicit_jst_for_trading_schedule_boundaries():
    now = SystemClock().now()

    assert now.utcoffset() == timedelta(hours=9)
    assert now.tzinfo is not None
