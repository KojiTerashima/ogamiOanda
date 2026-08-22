from datetime import datetime

import pandas as pd
import pytest

from ogami_oanda.application.services.market_analysis_service import (
    MarketAnalysisResult,
)
from ogami_oanda.application.services.order_planner import OrderPlanner
from ogami_oanda.application.services.position_portfolio_service import (
    PositionPortfolioService,
)
from ogami_oanda.application.services.position_service import PositionService
from ogami_oanda.domain.orders.models import (
    Direction,
    OrderContext,
    OrderIntent,
    OrderType,
)
from ogami_oanda.domain.positions.managed_position import ManagedPosition
from ogami_oanda.domain.positions.models import (
    OrderState,
    PositionSnapshot,
    TradeState,
)
from ogami_oanda.entrypoints.live import LiveApplication
from tests.fakes import (
    FakeBroker,
    FakeMarketData,
    FakeNotifier,
    FixedClock,
    InMemoryTradeHistoryRepository,
)


class _CandleAnalysis:
    def __init__(self, frame: pd.DataFrame) -> None:
        self.frame = frame
        self.calls = 0

    def analyze(
        self,
        pair: str,
        decision_time: str,
        *,
        current_price: float | None = None,
    ) -> MarketAnalysisResult:
        self.calls += 1
        peaks = type(
            "_Peaks",
            (),
            {"peaks_original": [{"count": 3, "direction": 1}]},
        )()
        return MarketAnalysisResult(
            (),
            {"M5": self.frame},
            {"M5": peaks},
        )


def _open_plan():
    return OrderPlanner().plan(
        OrderIntent(
            pair="USD_JPY",
            direction=Direction.BUY,
            order_type=OrderType.LIMIT,
            target=150.0,
            target_is_price=True,
            take_profit=0.2,
            take_profit_is_price=False,
            stop_loss=0.1,
            stop_loss_is_price=False,
            units=1000,
            name="live-candle",
            priority=1,
            order_timeout_min=30,
        ),
        OrderContext(150.0, "2026/01/02 10:00:00"),
    )


@pytest.mark.contract
def test_live_position_sync_uses_cached_real_m5_peak_and_previous_candle():
    clock = FixedClock(datetime(2026, 1, 2, 10, 5, 0))
    broker = FakeBroker()
    position_service = PositionService(
        broker,
        broker,
        FakeNotifier(),
        InMemoryTradeHistoryRepository(),
        clock,
    )
    portfolio = PositionPortfolioService(
        "USD_JPY",
        position_service,
        broker,
        broker,
    )
    position = (
        ManagedPosition.registered("live-candle", "USD_JPY")
        .with_order_plan(_open_plan(), datetime(2026, 1, 2, 10, 4, 20))
        .filled("trade-live-candle", datetime(2026, 1, 2, 10, 4, 30))
    )
    portfolio.slots[0] = position
    broker.trades["trade-live-candle"] = PositionSnapshot(
        "live-candle",
        "USD_JPY",
        OrderState.FILLED,
        TradeState.OPEN,
        trade_id="trade-live-candle",
        life=True,
        direction=1,
        target_price=150.0,
        current_stop_loss=149.9,
    )
    frame = pd.DataFrame(
        [
            {
                "time_jp": "2026/01/02 10:05:00",
                "open": 150.12,
                "close": 150.14,
                "high": 150.16,
                "low": 150.11,
            },
            {
                "time_jp": "2026/01/02 10:00:00",
                "open": 150.11,
                "close": 150.13,
                "high": 150.15,
                "low": 150.12,
            },
        ]
    )
    analysis = _CandleAnalysis(frame)
    application = LiveApplication(
        "USD_JPY",
        FakeMarketData({}, {"USD_JPY": 150.14}),
        analysis,
        OrderPlanner(),
        portfolio,
        clock,
    )

    initial = application.run_once(now=clock.now())
    clock.value = datetime(2026, 1, 2, 10, 5, 10)
    synced = application.run_once(now=clock.now())

    assert initial.analysis is not None
    assert initial.summary is None
    assert synced.analysis is None
    assert synced.summary is not None
    assert portfolio.slots[0] is not None
    assert portfolio.slots[0].runtime.current_stop_loss == pytest.approx(150.105)
    assert portfolio.slots[0].runtime.candle_stop_loss_done is True
    assert broker.commands == [
        (
            "amend_protection",
            ("trade-live-candle", None, 150.105),
        ),
    ]
