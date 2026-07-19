from datetime import datetime

import pytest

from ogami_oanda.application.services.order_planner import OrderPlanner
from ogami_oanda.application.services.portfolio import ActiveOrder
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


def _plan(name, priority, target=150.0, direction=Direction.BUY, source="line", line_strategy="test", linkage_id=None):
    metadata = {"source": source, "line_strategy": line_strategy}
    if linkage_id is not None:
        metadata["linkage_id"] = linkage_id
    return OrderPlanner().plan(
        OrderIntent("USD_JPY", direction, OrderType.LIMIT, target, True, 0.2, False, 0.1, False, 1000, name, priority, 30, metadata=metadata),
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

    assert result.accepted == ()
    assert result.rejected == (("near", "duplicate"), ("first", "tier_full"), ("overflow", "tier_full"))


@pytest.mark.contract
def test_position_portfolio_sorts_batch_by_current_price_before_deduplication():
    service, _ = _service()

    result = service.register_plans([_plan("farther", 1, 150.05), _plan("nearer", 1, 150.02)], submit=False)

    assert result.accepted == ("nearer",)
    assert result.rejected == (("farther", "duplicate"),)
    assert service.slots[0].snapshot.name == "nearer"


@pytest.mark.contract
def test_position_portfolio_active_orders_use_registered_runtime_values():
    service, _ = _service()
    service.register_plans(
        [_plan("sell", 1, 149.9, direction=Direction.SELL, source="line", line_strategy="future_break")],
        submit=False,
    )

    assert service._active_orders() == [
        ActiveOrder("sell", -1, 149.9, "line", "future_break"),
    ]

    duplicate = service.register_plans(
        [_plan("same", 1, 149.92, direction=Direction.SELL, source="line", line_strategy="future_break")],
        submit=False,
    )
    different_source = service.register_plans(
        [_plan("different-source", 1, 149.92, direction=Direction.SELL, source="counter", line_strategy="future_break")],
        submit=False,
    )

    assert duplicate.rejected == (("same", "duplicate"),)
    assert different_source.accepted == ("different-source",)


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


@pytest.mark.contract
def test_position_portfolio_restores_open_positions_into_global_first_empty_slots():
    service, broker = _service()
    service.register_plans([_plan("occupied", 1)], submit=False)
    broker.positions["trade-1"] = PositionSnapshot(
        "restored-1",
        "USD_JPY",
        OrderState.FILLED,
        TradeState.OPEN,
        trade_id="trade-1",
        life=True,
        direction=1,
        target_price=150.1,
    )
    broker.positions["trade-2"] = PositionSnapshot(
        "restored-2",
        "USD_JPY",
        OrderState.FILLED,
        TradeState.OPEN,
        trade_id="trade-2",
        life=True,
        direction=-1,
        target_price=149.8,
    )

    assert service.restore_open_positions() == ("restored-1", "restored-2")
    assert service.slots[1].snapshot.name == "restored-1"
    assert service.slots[2].snapshot.name == "restored-2"
    assert service.slots[1].runtime.direction == 1
    assert service.slots[2].runtime.target_price == 149.8


@pytest.mark.contract
def test_position_portfolio_sync_collects_events_and_executes_linkage_after_dry_run():
    service, broker = _service()
    result = service.register_plans([
        _plan("main", 1, direction=Direction.BUY, linkage_id="pair-1"),
        _plan("linked", 1, direction=Direction.SELL, linkage_id="pair-1"),
    ])
    assert result.accepted == ("main", "linked")
    broker.orders["order-1"] = PositionSnapshot(
        "main",
        "USD_JPY",
        OrderState.FILLED,
        TradeState.OPEN,
        order_id="order-1",
        trade_id="trade-1",
        life=True,
        unrealized_pl=0.2,
    )
    broker.orders["order-2"] = PositionSnapshot(
        "linked",
        "USD_JPY",
        OrderState.PENDING,
        TradeState.NONE,
        order_id="order-2",
        life=True,
    )

    dry_run = service.sync_all(dry_run=True)

    assert [command.action for command in dry_run.commands] == ["cancel_order"]
    assert [event.kind for event in dry_run.events] == ["trade_opened"]
    assert broker.commands == []
    assert service.slots[0].snapshot.order_state is OrderState.PENDING
    assert service.slots[1].snapshot.order_state is OrderState.PENDING

    synced = service.sync_all()

    assert [command.action for command in synced.commands] == ["cancel_order"]
    assert [event.kind for event in synced.events] == ["trade_opened", "order_cancelled"]
    assert synced.open == 1
    assert synced.pending == 0
    assert synced.close_events == ()
    assert broker.commands == [("cancel_order", ("order-2",))]
