from __future__ import annotations

import csv
from datetime import datetime, timedelta

import pytest

from ogami_oanda.adapters.repositories.csv_trade_history import (
    CsvTradeHistoryRepository,
)
from ogami_oanda.application.services.closure_reporting_service import (
    LEGACY_HISTORY_COLUMNS,
)
from ogami_oanda.application.services.order_planner import OrderPlanner
from ogami_oanda.application.services.position_portfolio_service import (
    PositionPortfolioService,
)
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
from ogami_oanda.domain.positions.models import (
    OrderState,
    PositionSnapshot,
    TradeState,
)
from tests.fakes import (
    FakeBroker,
    FakeNotifier,
    FixedClock,
    InMemoryTradeHistoryRepository,
)

# Frozen by test_position_control_filters_near_candidates_before_assigning_*
# in tests/test_characterization_position_and_inspection.py.
LEGACY_DEDUP_BOUNDARY_PIPS = 3


def _plan(
    name: str,
    *,
    priority: int = 1,
    target: float = 150.0,
    current_price: float = 150.0,
    direction: Direction = Direction.BUY,
    order_type: OrderType = OrderType.LIMIT,
    stop_loss: float = 0.1,
    order_timeout_min: int = 30,
    trade_timeout_min: int = 240,
    lc_change: tuple[dict[str, object], ...] = (),
    source: str = "line",
    line_strategy: str = "matrix",
    metadata: dict[str, object] | None = None,
):
    intent_metadata = {
        "source": source,
        "line_strategy": line_strategy,
        **(metadata or {}),
    }
    return OrderPlanner().plan(
        OrderIntent(
            pair="USD_JPY",
            direction=direction,
            order_type=order_type,
            target=target,
            target_is_price=True,
            take_profit=0.2,
            take_profit_is_price=False,
            stop_loss=stop_loss,
            stop_loss_is_price=False,
            units=1000,
            name=name,
            priority=priority,
            order_timeout_min=order_timeout_min,
            trade_timeout_min=trade_timeout_min,
            lc_change=lc_change,
            metadata=intent_metadata,
        ),
        OrderContext(current_price, "2026/01/02 10:00:00"),
    )


def _portfolio(
    *,
    history=None,
):
    clock = FixedClock(datetime(2026, 1, 2, 10, 0, 0))
    broker = FakeBroker()
    notifier = FakeNotifier()
    position_service = PositionService(
        broker,
        broker,
        notifier,
        history or InMemoryTradeHistoryRepository(),
        clock,
    )
    portfolio = PositionPortfolioService(
        "USD_JPY",
        position_service,
        broker,
        broker,
    )
    return portfolio, broker, notifier, clock


@pytest.mark.contract
def test_position_acceptance_matrix_includes_exact_three_pip_dedup_boundary():
    portfolio, _, _, _ = _portfolio()
    assert portfolio.register_plans([_plan("base")], submit=False).accepted == (
        "base",
    )
    exact_boundary = portfolio.register_plans(
        [
            _plan(
                "exact-boundary",
                target=150.0 + LEGACY_DEDUP_BOUNDARY_PIPS * 0.01,
            )
        ],
        submit=False,
    )
    outside_boundary = portfolio.register_plans(
        [_plan("outside-boundary", target=150.031)],
        submit=False,
    )

    assert exact_boundary.rejected == (("exact-boundary", "duplicate"),)
    assert outside_boundary.accepted == ("outside-boundary",)


@pytest.mark.contract
def test_position_acceptance_matrix_timeout_boundaries_and_opt_in():
    portfolio, broker, _, clock = _portfolio()
    service = portfolio.position_service
    started_at = clock.now()

    default_plan = _plan("default-trade-timeout", trade_timeout_min=1)
    default_trade = (
        ManagedPosition.registered("default-trade-timeout", "USD_JPY")
        .with_order_plan(default_plan, started_at)
        .filled("trade-default", started_at)
    )
    broker.trades["trade-default"] = PositionSnapshot(
        "default-trade-timeout",
        "USD_JPY",
        OrderState.FILLED,
        TradeState.OPEN,
        trade_id="trade-default",
        life=True,
        direction=1,
        target_price=150.0,
        current_stop_loss=149.9,
    )

    enabled_plan = _plan(
        "enabled-trade-timeout",
        target=150.1,
        trade_timeout_min=1,
        metadata={"trade_timeout_enabled": True},
    )
    enabled_trade = (
        ManagedPosition.registered("enabled-trade-timeout", "USD_JPY")
        .with_order_plan(enabled_plan, started_at)
        .filled("trade-enabled", started_at)
    )
    broker.trades["trade-enabled"] = PositionSnapshot(
        "enabled-trade-timeout",
        "USD_JPY",
        OrderState.FILLED,
        TradeState.OPEN,
        trade_id="trade-enabled",
        life=True,
        direction=1,
        target_price=150.1,
        current_stop_loss=150.0,
    )

    clock.value = started_at + timedelta(seconds=60)
    default_at_boundary = service.sync_result(default_trade)
    enabled_at_boundary = service.sync_result(enabled_trade)

    assert default_at_boundary.commands == ()
    assert default_at_boundary.position.runtime.close_requested is False
    assert [command.reason for command in enabled_at_boundary.commands] == [
        "trade_timeout"
    ]
    assert enabled_at_boundary.position.runtime.close_requested is True
    assert broker.commands == [
        ("close_trade", ("trade-enabled", None)),
    ]


@pytest.mark.contract
def test_position_acceptance_matrix_full_lifecycle_reporting_and_linkage(
    tmp_path,
):
    history_path = tmp_path / "nested" / "history.csv"
    history = CsvTradeHistoryRepository(history_path)
    portfolio, broker, notifier, clock = _portfolio(history=history)
    started_at = clock.now()
    linkage_id = "legacy-linkage-1"

    main_plan = _plan(
        "main-close-12345",
        current_price=149.9,
        order_type=OrderType.STOP,
        trade_timeout_min=1,
        lc_change=(
            {
                "exe": True,
                "trigger": 0.03,
                "ensure": 0.01,
                "time_after": 0,
            },
        ),
        metadata={
            "order_permission": False,
            "linkage_id": linkage_id,
            "name_ymdhms": "main-close_2026/01/02 10:00:00",
            "memo": "acceptance matrix",
        },
    )
    linked_pending_plan = _plan(
        "linked-pending",
        target=150.3,
        current_price=149.9,
        direction=Direction.SELL,
        metadata={"linkage_id": linkage_id},
    )
    registration = portfolio.register_plans(
        [linked_pending_plan, main_plan],
        submit=True,
    )

    assert registration.accepted == ("main-close-12345", "linked-pending")
    assert portfolio.summary() == portfolio.summary().__class__(
        watching=1,
        pending=1,
        open=0,
        closed=0,
    )
    assert len(broker.requests) == 1

    broker.orders["order-1"] = PositionSnapshot(
        "linked-pending",
        "USD_JPY",
        OrderState.PENDING,
        TradeState.NONE,
        order_id="order-1",
        life=True,
        direction=-1,
        target_price=150.3,
    )
    linked_open_plan = _plan(
        "linked-open",
        target=150.0,
        direction=Direction.SELL,
        stop_loss=0.05,
        metadata={"linkage_id": linkage_id},
    )
    linked_open = (
        ManagedPosition.registered("linked-open", "USD_JPY")
        .with_order_plan(linked_open_plan, started_at)
        .pending("order-existing")
        .filled("trade-existing", started_at)
        .with_runtime(current_stop_loss=150.2, unrealized_pl=0.3)
    )
    portfolio.slots[2] = linked_open
    broker.trades["trade-existing"] = PositionSnapshot(
        "linked-open",
        "USD_JPY",
        OrderState.FILLED,
        TradeState.OPEN,
        order_id="order-existing",
        trade_id="trade-existing",
        life=True,
        direction=-1,
        target_price=150.0,
        units=1000,
        current_stop_loss=150.2,
        unrealized_pl=0.3,
    )

    crossed = portfolio.sync_all(current_price=150.01)
    clock.value = started_at + timedelta(seconds=30)
    submitted = portfolio.sync_all(current_price=150.01)

    assert (crossed.watching, crossed.pending, crossed.open) == (1, 1, 1)
    assert crossed.commands == ()
    assert (submitted.watching, submitted.pending, submitted.open) == (0, 2, 1)
    assert [command.action for command in submitted.commands] == [
        "submit_order"
    ]
    assert len(broker.requests) == 2

    clock.value = started_at + timedelta(seconds=31)
    broker.orders["order-2"] = PositionSnapshot(
        "main-close-12345",
        "USD_JPY",
        OrderState.FILLED,
        TradeState.OPEN,
        order_id="order-2",
        trade_id="trade-main",
        life=True,
        direction=1,
        target_price=150.0,
        units=1000,
        current_stop_loss=149.9,
        unrealized_pl=0.3,
    )
    opened = portfolio.sync_all(current_price=150.0)

    assert (opened.watching, opened.pending, opened.open, opened.closed) == (
        0,
        0,
        2,
        1,
    )
    assert [event.kind for event in opened.events] == [
        "trade_opened",
        "order_cancelled",
    ]
    assert [(command.action, command.reason) for command in opened.commands] == [
        ("cancel_order", "linkage_trade_opened")
    ]
    assert not any(command.reason == "hedge_profit" for command in opened.commands)

    broker.trades["trade-main"] = broker.orders["order-2"]
    normal_lc = portfolio.sync_all(current_price=150.03)

    assert [(command.action, command.stop_loss_price) for command in normal_lc.commands] == [
        ("amend_stop_loss", pytest.approx(150.01))
    ]
    assert portfolio.slots[0].runtime.applied_lc_change_index == 0

    broker.trades["trade-main"] = PositionSnapshot(
        **{
            **broker.trades["trade-main"].__dict__,
            "current_stop_loss": 150.01,
            "current_price": 150.03,
        }
    )
    clock.value = datetime(2026, 1, 2, 10, 5, 10)
    candle_lc = portfolio.sync_all(
        current_price=150.14,
        candle_stop_loss=CandleStopLossInput(
            latest_peak={"count": 3, "direction": 1},
            previous_candle={
                "time_jp": "2026/01/02 10:00:00",
                "low": 150.12,
                "high": 150.15,
            },
        ),
    )

    assert [(command.action, command.stop_loss_price) for command in candle_lc.commands] == [
        ("amend_stop_loss", pytest.approx(150.105))
    ]
    assert portfolio.slots[0].runtime.candle_stop_loss_done is True

    broker.trades["trade-main"] = PositionSnapshot(
        **{
            **broker.trades["trade-main"].__dict__,
            "current_stop_loss": 150.105,
            "current_price": 150.14,
        }
    )
    clock.value = datetime(2026, 1, 2, 10, 6, 0)
    legacy_default_timeout = portfolio.sync_all(current_price=150.14)

    assert legacy_default_timeout.commands == ()
    assert portfolio.slots[0].runtime.close_requested is False

    clock.value = datetime(2026, 1, 2, 10, 6, 1)
    broker.trades["trade-main"] = PositionSnapshot(
        "main-close-12345",
        "USD_JPY",
        OrderState.FILLED,
        TradeState.CLOSED,
        order_id="order-2",
        trade_id="trade-main",
        life=False,
        direction=1,
        target_price=150.0,
        units=1000,
        current_stop_loss=150.105,
        realized_pl=-30,
        average_close_price=149.97,
        open_time="2026/01/02 10:00:31",
        close_time="2026/01/02 10:06:01",
        elapsed_seconds=330,
    )
    closed = portfolio.sync_all()
    duplicate_close = portfolio.sync_all()

    assert (closed.watching, closed.pending, closed.open, closed.closed) == (
        0,
        0,
        1,
        2,
    )
    assert [event.kind for event in closed.close_events] == ["trade_closed"]
    assert [(command.action, command.stop_loss_price) for command in closed.commands] == [
        ("amend_stop_loss", pytest.approx(150.05))
    ]
    assert portfolio.slots[2].runtime.linkage_done is True
    assert duplicate_close.events == ()

    with history_path.open(newline="", encoding="utf-8") as history_file:
        reader = csv.DictReader(history_file)
        rows = list(reader)

    assert tuple(reader.fieldnames or ()) == LEGACY_HISTORY_COLUMNS
    assert len(rows) == 1
    assert rows[0]["name"] == "main-close-12345"
    assert rows[0]["res"] == "-30"
    assert float(rows[0]["pl_per_units"]) == -3
    assert rows[0]["tradeID"] == "trade-main"

    analytics = portfolio.position_service.closure_reporting.analytics
    assert analytics.total_yen == -30
    assert analytics.total_pips == -3
    assert analytics.minus_yen_position_num == 1
    assert analytics.plus_yen_position_num == 0
    assert analytics.lc_change_num == 2
    assert analytics.before_latest_name == "main-close-12345"
    assert analytics.history_plus_minus[-1] == -3
    assert analytics.latest_summary()["res_sum"] == -30
    assert [
        message
        for message in notifier.messages
        if message[1] == "close"
    ] == [
        (
            "Trade closed: main-close-12345 -3.0p -30",
            "close",
            "USD_JPY",
        )
    ]
    assert broker.commands == [
        ("cancel_order", ("order-1",)),
        ("amend_protection", ("trade-main", None, 150.01)),
        ("amend_protection", ("trade-main", None, 150.105)),
        ("amend_protection", ("trade-existing", None, 150.05)),
    ]
