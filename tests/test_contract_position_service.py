from datetime import datetime

import pytest

from ogami_oanda.application.services.order_planner import OrderPlanner
from ogami_oanda.application.services.position_service import PositionService
from ogami_oanda.domain.orders.models import (
    Direction,
    OrderContext,
    OrderIntent,
    OrderType,
)
from ogami_oanda.domain.positions.managed_position import ManagedPosition
from ogami_oanda.domain.positions.models import OrderState, PositionSnapshot, TradeState
from ogami_oanda.strategy.position_management import ExitPolicy, StopLossPolicy
from tests.fakes import (
    FakeBroker,
    FakeNotifier,
    FixedClock,
    InMemoryTradeHistoryRepository,
)


def _order_plan():
    return OrderPlanner().plan(
        OrderIntent(
            pair="USD_JPY",
            direction=Direction.BUY,
            order_type=OrderType.MARKET,
            target=0,
            target_is_price=False,
            take_profit=0.2,
            take_profit_is_price=False,
            stop_loss=0.1,
            stop_loss_is_price=False,
            units=1000,
            name="position-test",
            priority=1,
            order_timeout_min=30,
        ),
        OrderContext(150.0, "2026/01/02 03:04:05"),
    )


@pytest.mark.contract
def test_position_service_register_sync_and_close_lifecycle():
    broker = FakeBroker()
    notifier = FakeNotifier()
    history = InMemoryTradeHistoryRepository()
    service = PositionService(broker, broker, notifier, history, FixedClock(datetime(2026, 1, 2, 3, 4, 5)))
    position = ManagedPosition.registered("position-test", "USD_JPY")

    pending = service.register(position, _order_plan())
    assert pending.snapshot.order_state is OrderState.PENDING
    assert pending.snapshot.order_id == "order-1"

    broker.positions["order-1"] = PositionSnapshot(
        name="position-test",
        pair="USD_JPY",
        order_state=OrderState.FILLED,
        trade_state=TradeState.OPEN,
        trade_id="trade-1",
        life=True,
    )
    opened = service.sync(pending)
    closed = service.close(opened)

    assert opened.snapshot.trade_state is TradeState.OPEN
    assert closed.snapshot.trade_state is TradeState.CLOSED
    assert closed.snapshot.life is False
    assert broker.commands == [("close_trade", ("trade-1", None))]
    assert history.records[0]["name"] == "position-test"


@pytest.mark.contract
def test_position_policies_preserve_timeout_and_stop_loss_rules():
    position = PositionSnapshot("name", "USD_JPY", OrderState.FILLED, TradeState.OPEN, trade_id="trade")
    assert ExitPolicy(10).should_close(position, 599) is False
    assert ExitPolicy(10).should_close(position, 600) is True

    policy = StopLossPolicy(trigger_range=0.1, ensure_range=0.05)
    assert policy.amended_stop_loss(150.0, 1, 150.09, 149.8) is None
    assert policy.amended_stop_loss(150.0, 1, 150.1, 149.8) == 150.05
    assert policy.amended_stop_loss(150.0, -1, 149.9, 150.2) == 149.95


@pytest.mark.contract
def test_position_service_syncs_cancelled_and_closed_broker_snapshots():
    broker = FakeBroker()
    service = PositionService(broker, broker, FakeNotifier(), InMemoryTradeHistoryRepository(), FixedClock(datetime(2026, 1, 2)))
    pending = ManagedPosition.registered("cancelled", "USD_JPY").pending("order-1")
    broker.orders["order-1"] = PositionSnapshot("cancelled", "USD_JPY", OrderState.CANCELLED, TradeState.NONE)

    cancelled = service.sync(pending)
    assert cancelled.snapshot.order_state is OrderState.CANCELLED
    assert cancelled.snapshot.life is False

    opened = ManagedPosition.registered("closed", "USD_JPY").filled("trade-1")
    broker.trades["trade-1"] = PositionSnapshot("closed", "USD_JPY", OrderState.FILLED, TradeState.CLOSED, trade_id="trade-1")

    closed = service.sync(opened)
    assert closed.snapshot.trade_state is TradeState.CLOSED
    assert closed.snapshot.life is False
