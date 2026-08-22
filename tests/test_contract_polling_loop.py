import pytest

from ogami_oanda.infrastructure.runtime import PollingLoop


@pytest.mark.contract
def test_polling_loop_owns_interval_and_supports_finite_execution():
    class _Timer:
        value = 10.0

        def now(self):
            return self.value

        def sleep(self, seconds):
            sleeps.append(seconds)
            self.value += seconds

    sleeps = []
    ticks = []
    timer = _Timer()
    loop = PollingLoop(interval_seconds=0.25, sleeper=timer.sleep, monotonic=timer.now)

    results = loop.run(lambda: ticks.append(len(ticks)) or ticks[-1], max_ticks=3)

    assert results == (0, 1, 2)
    assert sleeps == [0.25, 0.25]


@pytest.mark.contract
def test_polling_loop_zero_ticks_performs_no_work():
    loop = PollingLoop(sleeper=lambda seconds: (_ for _ in ()).throw(AssertionError("must not sleep")))

    assert loop.run(lambda: (_ for _ in ()).throw(AssertionError("must not tick")), max_ticks=0) == ()


@pytest.mark.contract
def test_polling_loop_skips_missed_deadlines_instead_of_drifting_after_slow_ticks():
    timeline = [0.0]
    sleeps = []

    def monotonic():
        return timeline[0]

    def slow_tick():
        timeline[0] += 1.4
        return len(sleeps)

    def sleep(seconds):
        sleeps.append(seconds)
        timeline[0] += seconds

    PollingLoop(interval_seconds=1, sleeper=sleep, monotonic=monotonic).run(slow_tick, max_ticks=2)

    assert sleeps == [pytest.approx(0.6)]
