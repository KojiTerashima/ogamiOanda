from datetime import datetime

import pytest

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
from ogami_oanda.domain.positions.models import OrderState, PositionSnapshot, TradeState
from ogami_oanda.infrastructure.config.models import TradingSettings
from tests.fakes import (
    FakeBroker,
    FakeNotifier,
    FixedClock,
    InMemoryTradeHistoryRepository,
)


def _plan(name, priority, target=150.0):
    return OrderPlanner().plan(
        OrderIntent("USD_JPY", Direction.BUY, OrderType.LIMIT, target, True, 0.2, False, 0.1, False, 1000, name, priority, 30, metadata={"source": "line", "line_strategy": "test"}),
        OrderContext(150.0, "2026/01/02 03:04:05"),
    )


def _service(settings=TradingSettings()):
    broker = FakeBroker()
    position_service = PositionService(broker, broker, FakeNotifier(), InMemoryTradeHistoryRepository(), FixedClock(datetime(2026, 1, 2)))
    return PositionPortfolioService("USD_JPY", position_service, broker, broker, settings), broker


@pytest.mark.contract
def test_position_portfolio_assigns_priority_tiers_and_watching_slots():
    service, broker = _service()

    result = service.register_plans([_plan("normal", 1), _plan("mid", 10, 150.1), _plan("high", 100, 150.2)], submit=False)

    assert result.accepted == ("normal", "mid", "high")
    assert service.slots[0].snapshot.name == "normal"
    assert service.slots[6].snapshot.name == "mid"
    assert service.slots[14].snapshot.name == "high"
    assert broker.requests == []


@pytest.mark.contract
def test_position_portfolio_rejects_near_batch_candidate_and_full_tier():
    service, _ = _service(TradingSettings(max_positions=2, normal_slot_count=1, mid_slot_count=1, high_slot_count=0))

    result = service.register_plans([_plan("first", 1, 150.0), _plan("near", 1, 150.02), _plan("overflow", 1, 150.2)], submit=False)

    assert result.accepted == ("first",)
    assert result.rejected == (("near", "duplicate"), ("overflow", "tier_full"))


@pytest.mark.contract
def test_position_portfolio_sync_restore_and_explicit_pending_cancellation():
    service, broker = _service()
    service.register_plans([_plan("pending", 1)], submit=True)
    broker.orders["order-1"] = PositionSnapshot("pending", "USD_JPY", OrderState.FILLED, TradeState.OPEN, order_id="order-1", trade_id="trade-1", life=True)

    summary = service.sync_all()
    assert summary.open == 1

    broker.positions["trade-2"] = PositionSnapshot("restored", "USD_JPY", OrderState.FILLED, TradeState.OPEN, trade_id="trade-2", life=True)
    assert service.restore_open_positions() == ("restored",)

    broker.orders["pending-2"] = PositionSnapshot("pending-2", "USD_JPY", OrderState.PENDING, TradeState.NONE, order_id="pending-2", life=True)
    assert service.cancel_pending_on_start(False) == ()
    assert service.cancel_pending_on_start(True) == ("pending-2",)
    assert broker.commands == [("cancel_order", ("pending-2",))]
