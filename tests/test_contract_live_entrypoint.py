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
