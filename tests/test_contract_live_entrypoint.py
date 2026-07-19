from datetime import datetime

import pytest

from ogami_oanda.application.services.market_analysis_service import (
    MarketAnalysisResult,
)
from ogami_oanda.application.services.order_planner import OrderPlanner
from ogami_oanda.application.services.position_portfolio_service import (
    PositionPortfolioService,
)
from ogami_oanda.application.services.position_service import PositionService
from ogami_oanda.domain.orders.models import Direction, OrderIntent, OrderType
from ogami_oanda.domain.positions.models import OrderState, PositionSnapshot, TradeState
from ogami_oanda.entrypoints.live import LiveApplication, build_live_application
from ogami_oanda.application.ports.market_data import MarketQuote
from ogami_oanda.infrastructure.config.models import AppSettings, RuntimeAccountConfig
from tests.fakes import (
    FakeBroker,
    FakeMarketData,
    FakeNotifier,
    FixedClock,
    InMemoryTradeHistoryRepository,
)


class _Analysis:
    def __init__(self, intent):
        self.intent = intent

    def analyze(self, pair, decision_time):
        return MarketAnalysisResult((self.intent,), {}, {})


class _NoAnalysis:
    def __init__(self):
        self.calls = 0

    def analyze(self, pair, decision_time, *, current_price=None):
        self.calls += 1
        return MarketAnalysisResult((), {}, {})


class _WideSpreadMarket(FakeMarketData):
    def current_quote(self, pair):
        mid = self.current_price(pair)
        return MarketQuote(pair, mid - 0.01, mid + 0.01, mid)


@pytest.mark.contract
def test_live_run_once_dry_run_registers_watching_position_without_submission():
    clock = FixedClock(datetime(2026, 1, 2, 3, 4, 5))
    broker = FakeBroker()
    position_service = PositionService(broker, broker, FakeNotifier(), InMemoryTradeHistoryRepository(), clock)
    portfolio = PositionPortfolioService("USD_JPY", position_service, broker, broker)
    intent = OrderIntent("USD_JPY", Direction.BUY, OrderType.LIMIT, 150.0, True, 10, False, 10, False, 1000, "line", 1, 0)
    application = LiveApplication("USD_JPY", FakeMarketData({}, {"USD_JPY": 150.2}), _Analysis(intent), OrderPlanner(), portfolio, clock)

    result = application.run_once(dry_run=True)

    assert result.registration.accepted == ("line",)
    assert broker.requests == []
    assert portfolio.summary().watching == 1


@pytest.mark.contract
def test_live_composition_cancels_pending_only_when_explicitly_enabled(candle_frame):
    settings = AppSettings({"primary": RuntimeAccountConfig("id", "token", "practice")})
    broker = FakeBroker()
    market = FakeMarketData({("USD_JPY", "M5"): candle_frame}, {"USD_JPY": 150.0})

    build_live_application(settings, market_data=market, broker_execution=broker, broker_query=broker, notifier=FakeNotifier(), history=InMemoryTradeHistoryRepository(), clock=FixedClock(datetime(2026, 1, 2)))
    assert broker.commands == []

    broker.orders["pending-1"] = PositionSnapshot("pending", "USD_JPY", OrderState.PENDING, TradeState.NONE, order_id="pending-1")
    build_live_application(settings, market_data=market, broker_execution=broker, broker_query=broker, notifier=FakeNotifier(), history=InMemoryTradeHistoryRepository(), clock=FixedClock(datetime(2026, 1, 2)), cancel_pending_on_start=True)
    assert broker.commands == [("cancel_order", ("pending-1",))]


@pytest.mark.contract
def test_live_scheduler_skips_sunday_without_requesting_a_quote():
    class _NoQuote:
        def current_quote(self, pair):
            raise AssertionError("Sunday must not query pricing")

    clock = FixedClock(datetime(2026, 1, 4, 10, 0, 0))
    broker = FakeBroker()
    service = PositionService(broker, broker, FakeNotifier(), InMemoryTradeHistoryRepository(), clock)
    application = LiveApplication("USD_JPY", _NoQuote(), _NoAnalysis(), OrderPlanner(), PositionPortfolioService("USD_JPY", service, broker, broker), clock)

    result = application.run_once()

    assert result.skipped == ("market_closed",)
    assert broker.requests == []
    assert broker.commands == []


@pytest.mark.contract
def test_live_scheduler_uses_update_only_for_wide_spread_and_dry_run_has_no_commands():
    clock = FixedClock(datetime(2026, 1, 2, 10, 1, 3))
    broker = FakeBroker()
    service = PositionService(broker, broker, FakeNotifier(), InMemoryTradeHistoryRepository(), clock)
    analysis = _NoAnalysis()
    market = _WideSpreadMarket({}, {"USD_JPY": 150.0})
    application = LiveApplication("USD_JPY", market, analysis, OrderPlanner(), PositionPortfolioService("USD_JPY", service, broker, broker), clock)

    result = application.run_once(dry_run=True)

    assert result.skipped == ("update_only",)
    assert analysis.calls == 0
    assert broker.requests == []
    assert broker.commands == []


@pytest.mark.contract
def test_live_run_forever_accepts_finite_ticks_without_sleeping():
    clock = FixedClock(datetime(2026, 1, 2, 10, 0, 0))
    broker = FakeBroker()
    service = PositionService(broker, broker, FakeNotifier(), InMemoryTradeHistoryRepository(), clock)
    application = LiveApplication("USD_JPY", FakeMarketData({}, {"USD_JPY": 150.0}), _NoAnalysis(), OrderPlanner(), PositionPortfolioService("USD_JPY", service, broker, broker), clock)

    results = application.run_forever(dry_run=True, sleeper=lambda seconds: (_ for _ in ()).throw(AssertionError("must not sleep after final tick")), max_ticks=1)

    assert len(results) == 1
    assert broker.requests == []
    assert broker.commands == []
