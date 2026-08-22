from datetime import datetime

import pytest

from ogami_oanda.application.services.order_planner import OrderPlanner
from ogami_oanda.application.services.position_service import (
    CandleStopLossInput,
    PositionService,
)
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


def _managed_plan(
    order_type=OrderType.STOP,
    order_timeout_min=1,
    lc_change=(),
    *,
    trade_timeout_min=240,
    metadata=None,
):
    plan_metadata = {"source": "line", "line_strategy": "test"}
    plan_metadata.update(metadata or {})
    return OrderPlanner().plan(
        OrderIntent(
            pair="USD_JPY",
            direction=Direction.BUY,
            order_type=order_type,
            target=150.0,
            target_is_price=True,
            take_profit=0.2,
            take_profit_is_price=False,
            stop_loss=0.1,
            stop_loss_is_price=False,
            units=1000,
            name="managed",
            priority=1,
            order_timeout_min=order_timeout_min,
            trade_timeout_min=trade_timeout_min,
            lc_change=lc_change,
            metadata=plan_metadata,
        ),
        OrderContext(149.9, "2026/01/02 03:04:05"),
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
    assert pending.runtime.order_plan == _order_plan()
    assert pending.runtime.direction == 1
    assert pending.runtime.target_price == 150.0
    assert pending.runtime.registered_at == datetime(2026, 1, 2, 3, 4, 5)

    broker.positions["order-1"] = PositionSnapshot(
        name="position-test",
        pair="USD_JPY",
        order_state=OrderState.FILLED,
        trade_state=TradeState.OPEN,
        trade_id="trade-1",
        life=True,
    )
    opened = service.sync(pending)
    close_requested = service.close(opened)

    assert opened.snapshot.trade_state is TradeState.OPEN
    assert opened.runtime.order_plan == pending.runtime.order_plan
    assert opened.runtime.filled_at == datetime(2026, 1, 2, 3, 4, 5)
    assert close_requested.snapshot.trade_state is TradeState.OPEN
    assert close_requested.snapshot.life is True
    assert close_requested.runtime.close_requested is True
    assert history.records == []

    broker.trades["trade-1"] = PositionSnapshot(
        name="position-test",
        pair="USD_JPY",
        order_state=OrderState.FILLED,
        trade_state=TradeState.CLOSED,
        trade_id="trade-1",
        direction=1,
        target_price=150.0,
        units=1000,
        realized_pl=250,
        average_close_price=150.25,
    )
    closed = service.sync(close_requested)

    assert closed.snapshot.trade_state is TradeState.CLOSED
    assert closed.snapshot.life is False
    assert broker.commands == [("close_trade", ("trade-1", None))]
    assert history.records[0]["name"] == "position-test"
    assert history.records[0]["res"] == "250"
    assert history.records[0]["pl_per_units"] == 25.0


@pytest.mark.contract
def test_position_policies_preserve_timeout_and_stop_loss_rules():
    position = PositionSnapshot("name", "USD_JPY", OrderState.FILLED, TradeState.OPEN, trade_id="trade")
    assert ExitPolicy(10, trade_timeout_enabled=True).should_close(position, 599) is False
    assert ExitPolicy(10, trade_timeout_enabled=True).should_close(position, 600) is True

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


@pytest.mark.contract
def test_position_service_watching_dry_run_and_submit_decisions():
    broker = FakeBroker()
    clock = FixedClock(datetime(2026, 1, 2, 10, 0, 0))
    service = PositionService(broker, broker, FakeNotifier(), InMemoryTradeHistoryRepository(), clock)
    watching = service.register(ManagedPosition.registered("managed", "USD_JPY"), _managed_plan(), submit=False)

    crossed = service.sync_result(watching, current_price=150.01)
    clock.value = datetime(2026, 1, 2, 10, 0, 31)
    dry_run = service.sync_result(crossed.position, current_price=150.01, dry_run=True)
    submitted = service.sync_result(crossed.position, current_price=150.01)

    assert dry_run.position.snapshot.order_state is OrderState.WATCHING
    assert [command.action for command in dry_run.commands] == ["submit_order"]
    assert submitted.position.snapshot.order_state is OrderState.PENDING
    assert submitted.position.snapshot.order_id == "order-1"
    assert len(broker.requests) == 1


@pytest.mark.contract
def test_position_service_cancels_timed_out_pending_order():
    broker = FakeBroker()
    clock = FixedClock(datetime(2026, 1, 2, 10, 0, 0))
    service = PositionService(broker, broker, FakeNotifier(), InMemoryTradeHistoryRepository(), clock)
    pending = service.register(ManagedPosition.registered("managed", "USD_JPY"), _managed_plan(), submit=True)
    broker.orders["order-1"] = PositionSnapshot("managed", "USD_JPY", OrderState.PENDING, TradeState.NONE, order_id="order-1", life=True)
    clock.value = datetime(2026, 1, 2, 10, 1, 1)

    result = service.sync_result(pending)

    assert result.position.snapshot.order_state is OrderState.CANCELLED
    assert [command.action for command in result.commands] == ["cancel_order"]
    assert broker.commands == [("cancel_order", ("order-1",))]


@pytest.mark.contract
def test_position_service_amends_stop_loss_and_reports_close_once():
    broker = FakeBroker()
    notifier = FakeNotifier()
    history = InMemoryTradeHistoryRepository()
    clock = FixedClock(datetime(2026, 1, 2, 10, 0, 0))
    service = PositionService(broker, broker, notifier, history, clock)
    plan = _managed_plan(lc_change=({"exe": True, "trigger": 0.03, "ensure": 0.01, "time_after": 0},))
    position = service.register(ManagedPosition.registered("managed", "USD_JPY"), plan, submit=True).filled("trade-1", clock.now())
    broker.trades["trade-1"] = PositionSnapshot(
        "managed",
        "USD_JPY",
        OrderState.FILLED,
        TradeState.OPEN,
        trade_id="trade-1",
        life=True,
    )

    amended = service.sync_result(position, current_price=150.03)

    assert amended.position.runtime.current_stop_loss == pytest.approx(150.01)
    assert amended.position.runtime.applied_lc_change_index == 0
    assert broker.commands == [("amend_protection", ("trade-1", None, 150.01))]

    broker.trades["trade-1"] = PositionSnapshot(
        "managed",
        "USD_JPY",
        OrderState.FILLED,
        TradeState.CLOSED,
        trade_id="trade-1",
        life=False,
        direction=1,
        target_price=150.0,
        units=1000,
        realized_pl=200,
        average_close_price=150.2,
        elapsed_seconds=600,
    )
    dry_close = service.sync_result(amended.position, dry_run=True)
    first_close = service.sync_result(amended.position)
    duplicate_close = service.sync_result(amended.position)

    assert [event.kind for event in dry_close.events] == ["trade_closed"]
    assert first_close.position.snapshot.trade_state is TradeState.CLOSED
    assert [event.kind for event in first_close.events] == ["trade_closed"]
    assert duplicate_close.events == ()
    assert len(history.records) == 1
    assert history.records[0]["name"] == "managed"
    assert history.records[0]["pl_per_units"] == 20.0


@pytest.mark.contract
def test_position_service_amends_stop_loss_from_real_peak_and_previous_candle():
    broker = FakeBroker()
    clock = FixedClock(datetime(2026, 1, 2, 10, 5, 10))
    service = PositionService(
        broker,
        broker,
        FakeNotifier(),
        InMemoryTradeHistoryRepository(),
        clock,
    )
    plan = _managed_plan()
    position = (
        ManagedPosition.registered("candle-managed", "USD_JPY")
        .with_order_plan(plan, datetime(2026, 1, 2, 10, 4, 30))
        .filled("trade-candle", datetime(2026, 1, 2, 10, 4, 40))
    )
    broker.trades["trade-candle"] = PositionSnapshot(
        "candle-managed",
        "USD_JPY",
        OrderState.FILLED,
        TradeState.OPEN,
        trade_id="trade-candle",
        life=True,
        direction=1,
        target_price=150.0,
        current_stop_loss=149.9,
    )
    candle_input = CandleStopLossInput(
        latest_peak={"count": 3, "direction": 1},
        previous_candle={
            "time_jp": "2026/01/02 10:00:00",
            "low": 150.12,
            "high": 150.15,
        },
    )

    result = service.sync_result(
        position,
        current_price=150.14,
        candle_stop_loss=candle_input,
    )

    assert result.reason == "candle_lc_amended"
    assert result.position.runtime.current_stop_loss == pytest.approx(150.105)
    assert result.position.runtime.candle_stop_loss_done is True
    assert [command.reason for command in result.commands] == [
        "candle_lc_trigger",
    ]
    assert broker.commands == [
        ("amend_protection", ("trade-candle", None, 150.105)),
    ]


@pytest.mark.contract
def test_position_service_dry_run_never_mutates_cancel_close_or_amend():
    broker = FakeBroker()
    start = datetime(2026, 1, 2, 10, 0, 0)
    clock = FixedClock(datetime(2026, 1, 2, 10, 1, 1))
    service = PositionService(
        broker,
        broker,
        FakeNotifier(),
        InMemoryTradeHistoryRepository(),
        clock,
    )

    pending_plan = _managed_plan(order_timeout_min=1)
    pending = (
        ManagedPosition.registered("pending-dry", "USD_JPY")
        .with_order_plan(pending_plan, start)
        .pending("pending-dry")
    )
    broker.orders["pending-dry"] = PositionSnapshot(
        "pending-dry",
        "USD_JPY",
        OrderState.PENDING,
        TradeState.NONE,
        order_id="pending-dry",
        life=True,
    )
    cancel = service.sync_result(pending, dry_run=True)

    timeout_plan = _managed_plan(
        trade_timeout_min=1,
        metadata={"trade_timeout_enabled": True},
    )
    timed_trade = (
        ManagedPosition.registered("close-dry", "USD_JPY")
        .with_order_plan(timeout_plan, start)
        .filled("close-dry", start)
    )
    broker.trades["close-dry"] = PositionSnapshot(
        "close-dry",
        "USD_JPY",
        OrderState.FILLED,
        TradeState.OPEN,
        trade_id="close-dry",
        life=True,
        target_price=150.0,
        current_stop_loss=149.9,
    )
    close = service.sync_result(
        timed_trade,
        current_price=150.0,
        dry_run=True,
    )

    amend_plan = _managed_plan(
        lc_change=(
            {
                "exe": True,
                "trigger": 0.03,
                "ensure": 0.01,
                "time_after": 0,
            },
        ),
    )
    amended_trade = (
        ManagedPosition.registered("amend-dry", "USD_JPY")
        .with_order_plan(amend_plan, start)
        .filled("amend-dry", start)
    )
    broker.trades["amend-dry"] = PositionSnapshot(
        "amend-dry",
        "USD_JPY",
        OrderState.FILLED,
        TradeState.OPEN,
        trade_id="amend-dry",
        life=True,
        target_price=150.0,
        current_stop_loss=149.9,
    )
    amend = service.sync_result(
        amended_trade,
        current_price=150.03,
        dry_run=True,
    )
    direct_close = service.close(amended_trade, dry_run=True)

    assert [command.action for command in cancel.commands] == ["cancel_order"]
    assert [command.action for command in close.commands] == ["close_trade"]
    assert [command.action for command in amend.commands] == ["amend_stop_loss"]
    assert direct_close == amended_trade
    assert broker.requests == []
    assert broker.commands == []
