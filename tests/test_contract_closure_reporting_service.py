from datetime import datetime

import pytest

from ogami_oanda.application.services.closure_reporting_service import (
    LEGACY_HISTORY_COLUMNS,
    ClosureReportingService,
    PortfolioAnalytics,
)
from ogami_oanda.application.services.order_planner import OrderPlanner
from ogami_oanda.domain.orders.models import (
    Direction,
    OrderContext,
    OrderIntent,
    OrderType,
)
from ogami_oanda.domain.positions.managed_position import ManagedPosition
from ogami_oanda.domain.positions.models import (
    OrderState,
    PositionEvent,
    PositionSnapshot,
    TradeState,
)
from tests.fakes import FakeNotifier, InMemoryTradeHistoryRepository


@pytest.mark.contract
def test_closure_reporting_preserves_legacy_columns_totals_and_deduplication():
    plan = OrderPlanner().plan(
        OrderIntent(
            "USD_JPY",
            Direction.BUY,
            OrderType.LIMIT,
            150.0,
            True,
            0.2,
            False,
            0.1,
            False,
            1000,
            "close-test-12:00",
            1,
            30,
            metadata={"name_ymdhms": "close-test_2026/01/02 12:00:00", "memo": "close memo"},
        ),
        OrderContext(150.0, "2026/01/02 12:00:00", move_average=0.05),
    )
    position = ManagedPosition.registered(plan.intent.name, "USD_JPY").with_order_plan(
        plan,
        datetime(2026, 1, 2, 12, 0, 0),
    ).pending("order-1").filled("trade-1", datetime(2026, 1, 2, 12, 0, 30))
    broker_snapshot = PositionSnapshot(
        plan.intent.name,
        "USD_JPY",
        OrderState.FILLED,
        TradeState.CLOSED,
        order_id="order-1",
        trade_id="trade-1",
        direction=1,
        target_price=150.0,
        units=1000,
        realized_pl=200,
        average_close_price=150.2,
        elapsed_seconds=600,
    )
    event = PositionEvent(
        "trade_closed:trade-1",
        "trade_closed",
        plan.intent.name,
        "USD_JPY",
        datetime(2026, 1, 2, 12, 10, 30),
        {"position": position, "broker_snapshot": broker_snapshot},
    )
    history = InMemoryTradeHistoryRepository()
    notifier = FakeNotifier()
    analytics = PortfolioAnalytics()
    service = ClosureReportingService(history, notifier, analytics)

    first = service.report(event)
    second = service.report(event)

    assert first is not None
    assert tuple(first) == LEGACY_HISTORY_COLUMNS
    assert second is None
    assert len(history.records) == 1
    assert analytics.total_yen == 200
    assert analytics.total_pips == 20
    assert analytics.total_yen_max == 200
    assert analytics.total_yen_min == 0
    assert analytics.plus_yen_position_num == 1
    assert analytics.before_latest_name == "close-test-12:00"
    assert analytics.history_plus_minus == [20]
    assert notifier.messages
