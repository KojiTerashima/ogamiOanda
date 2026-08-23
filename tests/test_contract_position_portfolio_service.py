from datetime import datetime

import pytest

from ogami_oanda.application.ports.broker import ExecutionResult, MutationState
from ogami_oanda.application.ports.broker import OrderSubmissionResult
from ogami_oanda.application.ports.position_state import account_identity_hash
from ogami_oanda.application.services.order_planner import OrderPlanner
from ogami_oanda.application.services.portfolio import ActiveOrder
from ogami_oanda.application.services.position_portfolio_service import (
    PortfolioStartupState,
    PositionStatePersistenceError,
    PositionPortfolioService,
)
from ogami_oanda.application.services.position_service import PositionService
from ogami_oanda.domain.orders.models import (
    Direction,
    OrderContext,
    OrderIntent,
    OrderType,
)
from ogami_oanda.domain.positions.models import (
    OrderState,
    PositionSnapshot,
    SubmissionPhase,
    TradeState,
)
from ogami_oanda.infrastructure.config.models import TradingSettings
from tests.fakes import (
    FakeBroker,
    FakeNotifier,
    FixedClock,
    InMemoryTradeHistoryRepository,
)


def _plan(name, priority, target=150.0, direction=Direction.BUY, source="line", line_strategy="test", linkage_id=None, order_type=OrderType.LIMIT):
    metadata = {"source": source, "line_strategy": line_strategy}
    if linkage_id is not None:
        metadata["linkage_id"] = linkage_id
    return OrderPlanner().plan(
        OrderIntent("USD_JPY", direction, order_type, target, True, 0.2, False, 0.1, False, 1000, name, priority, 30, metadata=metadata),
        OrderContext(150.0, "2026/01/02 03:04:05"),
    )


class _StateRepository:
    def __init__(self, *, fail_on_save=False, trace=None):
        self.fail_on_save = fail_on_save
        self.saved = []
        self.trace = trace

    def save(self, checkpoint):
        if self.fail_on_save:
            raise OSError("checkpoint unavailable")
        self.saved.append(checkpoint)
        if self.trace is not None:
            self.trace.append(
                (
                    "save",
                    tuple(item.action for item in checkpoint.pending_mutations),
                )
            )

    def load(self, **_kwargs):
        raise AssertionError("load is not part of this write-ahead test")


def _service(settings=TradingSettings(), *, state_repository=None, broker=None):
    broker = broker or FakeBroker()
    position_service = PositionService(broker, broker, FakeNotifier(), InMemoryTradeHistoryRepository(), FixedClock(datetime(2026, 1, 2)))
    service = PositionPortfolioService(
        "USD_JPY",
        position_service,
        broker,
        broker,
        settings,
        state_repository=state_repository,
        account_hash=account_identity_hash("id"),
    )
    service.startup_state = PortfolioStartupState.READY
    return service, broker


@pytest.mark.contract
def test_position_portfolio_writes_prepared_and_submitting_before_broker_submit():
    state_repository = _StateRepository()
    service, broker = _service(state_repository=state_repository)

    result = service.register_plans([_plan("write-ahead", 1)], submit=True)

    assert result.accepted == ("write-ahead",)
    assert len(broker.requests) == 1
    phases = [
        checkpoint.slots[0].runtime.submission_phase
        for checkpoint in state_repository.saved
        if checkpoint.slots[0] is not None
    ]
    assert phases == [
        SubmissionPhase.PREPARED,
        SubmissionPhase.SUBMITTING,
        SubmissionPhase.PENDING,
    ]
    assert state_repository.saved[1].pending_mutations[0].action == "submit_order"
    assert state_repository.saved[1].pending_mutations[0].client_reference
    assert state_repository.saved[-1].pending_mutations == ()


@pytest.mark.contract
def test_position_portfolio_never_submits_when_prepared_checkpoint_fails():
    state_repository = _StateRepository(fail_on_save=True)
    service, broker = _service(state_repository=state_repository)

    with pytest.raises(PositionStatePersistenceError, match="checkpoint unavailable"):
        service.register_plans([_plan("blocked", 1)], submit=True)

    assert broker.requests == []
    assert broker.commands == []
    assert service.slots[0] is None


@pytest.mark.contract
def test_position_portfolio_never_mutates_without_transaction_cursor():
    class _MissingCursorBroker(FakeBroker):
        def account_capabilities(self):
            from ogami_oanda.application.ports.broker import AccountCapabilities

            return AccountCapabilities("id", True, None)

    state_repository = _StateRepository()
    broker = _MissingCursorBroker()
    service, _ = _service(
        state_repository=state_repository,
        broker=broker,
    )

    with pytest.raises(PositionStatePersistenceError, match="transaction cursor"):
        service.register_plans([_plan("missing-cursor", 1)], submit=True)

    assert broker.requests == []
    assert broker.commands == []


@pytest.mark.contract
def test_position_portfolio_does_not_advance_cursor_when_mutation_begins():
    state_repository = _StateRepository()
    broker = FakeBroker()
    broker.transactions = __import__(
        "ogami_oanda.application.ports.broker",
        fromlist=["BrokerTransactionBatch"],
    ).BrokerTransactionBatch((), "101")
    service, _ = _service(
        state_repository=state_repository,
        broker=broker,
    )
    service.transaction_cursor = "100"

    service.register_plans([_plan("cursor-stable", 1)], submit=True)

    journal = next(
        checkpoint
        for checkpoint in state_repository.saved
        if checkpoint.pending_mutations
    )
    assert journal.transaction_cursor == "100"


class _TracingBroker(FakeBroker):
    def __init__(self, trace, *, unknown_action=None):
        super().__init__()
        self.trace = trace
        self.unknown_action = unknown_action

    def submit(self, request):
        self.trace.append(("broker", "submit_order"))
        return super().submit(request)

    def cancel_order(self, order_id):
        self.trace.append(("broker", "cancel_order"))
        if self.unknown_action == "cancel_order":
            return ExecutionResult(
                False,
                message="cancel outcome unknown",
                state=MutationState.UNKNOWN,
            )
        return super().cancel_order(order_id)

    def close_trade(self, trade_id, units=None):
        self.trace.append(("broker", "close_trade"))
        if self.unknown_action == "close_trade":
            return ExecutionResult(
                False,
                message="close outcome unknown",
                state=MutationState.UNKNOWN,
            )
        return super().close_trade(trade_id, units)

    def amend_protection(self, trade_id, take_profit_price, stop_loss_price):
        self.trace.append(("broker", "amend_stop_loss"))
        if self.unknown_action == "amend_stop_loss":
            return ExecutionResult(
                False,
                message="amend outcome unknown",
                state=MutationState.UNKNOWN,
            )
        return super().amend_protection(
            trade_id,
            take_profit_price,
            stop_loss_price,
        )


@pytest.mark.contract
def test_position_portfolio_journals_watching_submit_before_broker_call():
    trace = []
    state_repository = _StateRepository(trace=trace)
    broker = _TracingBroker(trace)
    service, _ = _service(state_repository=state_repository, broker=broker)
    service.register_plans(
        [_plan("watching", 1, order_type=OrderType.STOP)],
        submit=False,
    )
    service.slots[0] = service.slots[0].with_runtime(
        registered_at=datetime(2026, 1, 2, 0, 0, 0),
    )
    service.position_service.clock.value = datetime(2026, 1, 2, 0, 0, 0)
    service.sync_all(current_price=150.01)
    service.position_service.clock.value = datetime(2026, 1, 2, 0, 0, 31)
    service.sync_all(current_price=150.01)

    broker_index = trace.index(("broker", "submit_order"))
    assert ("save", ("submit_order",)) in trace[:broker_index]
    assert state_repository.saved[-1].pending_mutations == ()


@pytest.mark.contract
def test_watching_terminal_submit_quarantines_and_blocks_later_orders():
    class _TerminalBroker(FakeBroker):
        def submit(self, request):
            self.requests.append(request)
            return OrderSubmissionResult.terminal(
                "entry reduced existing trade",
                affected_trade_ids=("existing-trade",),
            )

    state_repository = _StateRepository()
    broker = _TerminalBroker()
    service, _ = _service(
        state_repository=state_repository,
        broker=broker,
    )
    service.register_plans(
        [_plan("watch-terminal", 1, order_type=OrderType.STOP)],
        submit=False,
    )
    service.slots[0] = service.slots[0].with_runtime(
        registered_at=datetime(2026, 1, 2, 0, 0, 0),
    )
    service.position_service.clock.value = datetime(2026, 1, 2, 0, 0, 0)
    service.sync_all(current_price=150.01)
    service.position_service.clock.value = datetime(2026, 1, 2, 0, 0, 31)

    service.sync_all(current_price=150.01)
    registration = service.register_plans(
        [_plan("blocked-after-terminal", 1, 150.2)],
        submit=True,
    )

    assert service.startup_state is PortfolioStartupState.QUARANTINED
    assert registration.rejected == (
        ("blocked-after-terminal", "portfolio_quarantined"),
    )
    assert len(broker.requests) == 1


@pytest.mark.contract
@pytest.mark.parametrize(
    "action",
    ["cancel_order", "close_trade", "amend_stop_loss"],
)
def test_position_portfolio_journals_each_mutation_and_keeps_unknown(action):
    trace = []
    state_repository = _StateRepository(trace=trace)
    broker = _TracingBroker(trace, unknown_action=action)
    service, _ = _service(state_repository=state_repository, broker=broker)
    plan = _plan("mutation", 1)
    position = service.position_service.prepare(
        __import__(
            "ogami_oanda.domain.positions.managed_position",
            fromlist=["ManagedPosition"],
        ).ManagedPosition.registered("mutation", "USD_JPY"),
        plan,
    )

    if action == "cancel_order":
        position = position.pending("order-1")
        broker.orders["order-1"] = PositionSnapshot(
            "mutation",
            "USD_JPY",
            OrderState.PENDING,
            TradeState.NONE,
            order_id="order-1",
            life=True,
        )
        service.position_service.clock.value = datetime(2026, 1, 2, 0, 31, 0)
    else:
        position = position.filled(
            "trade-1",
            datetime(2026, 1, 2, 0, 0, 0),
        ).with_runtime(current_stop_loss=149.9)
        broker.trades["trade-1"] = PositionSnapshot(
            "mutation",
            "USD_JPY",
            OrderState.FILLED,
            TradeState.OPEN,
            trade_id="trade-1",
            life=True,
            direction=1,
            target_price=150.0,
            current_stop_loss=149.9,
        )
        if action == "close_trade":
            position = position.with_runtime(
                order_plan=OrderPlanner().plan(
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
                        "mutation",
                        1,
                        30,
                        trade_timeout_min=1,
                        metadata={"trade_timeout_enabled": True},
                    ),
                    OrderContext(150.0, "2026/01/02 00:00:00"),
                )
            )
            service.position_service.clock.value = datetime(2026, 1, 2, 0, 1, 0)
        else:
            position = position.with_runtime(
                order_plan=OrderPlanner().plan(
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
                        "mutation",
                        1,
                        30,
                        lc_change=(
                            {
                                "exe": True,
                                "trigger": 0.03,
                                "ensure": 0.01,
                                "time_after": 0,
                            },
                        ),
                    ),
                    OrderContext(150.0, "2026/01/02 00:00:00"),
                )
            )

    service.slots[0] = position
    service.sync_all(current_price=150.03)

    broker_index = trace.index(("broker", action))
    assert ("save", (action,)) in trace[:broker_index]
    assert state_repository.saved[-1].pending_mutations[0].action == action


@pytest.mark.contract
def test_confirmed_startup_cancel_clears_journal_in_checkpoint():
    state_repository = _StateRepository()
    service, broker = _service(state_repository=state_repository)
    broker.orders["pending-1"] = PositionSnapshot(
        "pending",
        "USD_JPY",
        OrderState.PENDING,
        TradeState.NONE,
        order_id="pending-1",
        life=True,
    )

    assert service.cancel_pending_on_start(True) == ("pending-1",)

    assert state_repository.saved[-1].pending_mutations == ()


@pytest.mark.contract
def test_terminal_entry_effect_quarantines_portfolio_and_stops_later_submits():
    class _TerminalBroker(FakeBroker):
        def submit(self, request):
            self.requests.append(request)
            return OrderSubmissionResult.terminal(
                "entry reduced existing trade",
                order_id="order-terminal",
                affected_trade_ids=("existing-trade",),
            )

    broker = _TerminalBroker()
    service, _ = _service(broker=broker)

    first = service.register_plans([_plan("terminal", 1)], submit=True)
    second = service.register_plans([_plan("blocked", 1, 150.2)], submit=True)

    assert first.rejected == (("terminal", "terminal_broker_effect"),)
    assert second.rejected == (("blocked", "portfolio_quarantined"),)
    assert len(broker.requests) == 1


@pytest.mark.contract
def test_terminal_entry_effect_stops_remaining_submits_in_same_batch():
    class _TerminalBroker(FakeBroker):
        def submit(self, request):
            self.requests.append(request)
            return OrderSubmissionResult.terminal(
                "entry closed existing trade",
                affected_trade_ids=("existing-trade",),
            )

    broker = _TerminalBroker()
    service, _ = _service(broker=broker)

    result = service.register_plans(
        [_plan("terminal", 1), _plan("blocked", 1, 150.2)],
        submit=True,
    )

    assert result.rejected == (
        ("terminal", "terminal_broker_effect"),
        ("blocked", "portfolio_quarantined"),
    )
    assert len(broker.requests) == 1


@pytest.mark.contract
def test_unknown_submit_stops_batch_and_preserves_journal():
    class _UnknownBroker(FakeBroker):
        def submit(self, request):
            self.requests.append(request)
            return OrderSubmissionResult.unknown("submit outcome unknown")

    state_repository = _StateRepository()
    broker = _UnknownBroker()
    service, _ = _service(
        state_repository=state_repository,
        broker=broker,
    )

    result = service.register_plans(
        [_plan("unknown", 1), _plan("blocked", 1, 150.2)],
        submit=True,
    )

    assert result.accepted == ("unknown",)
    assert result.rejected == (("blocked", "broker_reconciliation"),)
    assert len(broker.requests) == 1
    assert service.pending_mutations[0].position_name == "unknown"
    assert state_repository.saved[-1].pending_mutations[0].position_name == "unknown"


@pytest.mark.contract
def test_pending_mutation_blocks_direct_portfolio_sync():
    state_repository = _StateRepository()
    broker = FakeBroker()
    service, _ = _service(
        state_repository=state_repository,
        broker=broker,
    )
    plan = _plan("blocked-sync", 1)
    service.slots[0] = service.position_service.prepare(
        __import__(
            "ogami_oanda.domain.positions.managed_position",
            fromlist=["ManagedPosition"],
        ).ManagedPosition.registered("blocked-sync", "USD_JPY"),
        plan,
    ).pending("order-1").with_runtime(
        registered_at=datetime(2026, 1, 2, 0, 0, 0),
    )
    service.position_service.clock.value = datetime(2026, 1, 2, 0, 31, 0)
    broker.orders["order-1"] = PositionSnapshot(
        "blocked-sync",
        "USD_JPY",
        OrderState.PENDING,
        TradeState.NONE,
        order_id="order-1",
        life=True,
    )
    service.pending_mutations = (
        __import__(
            "ogami_oanda.application.ports.position_state",
            fromlist=["PendingBrokerMutation"],
        ).PendingBrokerMutation(
            "submit_order",
            "blocked-sync",
            plan.broker_request.client_reference,
        ),
    )
    service.transaction_cursor = "100"

    summary = service.sync_all(current_price=150.1, dry_run=False)

    assert summary.pending == 1
    assert broker.requests == []
    assert broker.commands == []
    assert service.pending_mutations


@pytest.mark.contract
def test_direct_portfolio_sync_resumes_after_authoritative_reconciliation():
    state_repository = _StateRepository()
    broker = FakeBroker()
    service, _ = _service(
        state_repository=state_repository,
        broker=broker,
    )
    plan = _plan("sync-reconcile", 1)
    service.slots[0] = service.position_service.prepare(
        __import__(
            "ogami_oanda.domain.positions.managed_position",
            fromlist=["ManagedPosition"],
        ).ManagedPosition.registered("sync-reconcile", "USD_JPY"),
        plan,
    ).pending("order-1")
    broker.orders["order-1"] = PositionSnapshot(
        "sync-reconcile",
        "USD_JPY",
        OrderState.CANCELLED,
        TradeState.NONE,
        order_id="order-1",
        life=False,
    )
    service.pending_mutations = (
        __import__(
            "ogami_oanda.application.ports.position_state",
            fromlist=["PendingBrokerMutation"],
        ).PendingBrokerMutation(
            "cancel_order",
            "sync-reconcile",
            plan.broker_request.client_reference,
            "order-1",
            "timeout",
        ),
    )
    service.transaction_cursor = "100"
    service.startup_state = PortfolioStartupState.RECONCILING

    summary = service.sync_all(current_price=150.1, dry_run=False)

    assert service.pending_mutations == ()
    assert service.startup_state is PortfolioStartupState.READY
    assert summary.pending == 0
    assert service.slots[0] is not None
    assert service.slots[0].snapshot.order_state is OrderState.CANCELLED


@pytest.mark.contract
def test_unknown_mutation_stops_remaining_positions_in_same_sync():
    trace = []
    state_repository = _StateRepository(trace=trace)
    broker = _TracingBroker(trace, unknown_action="cancel_order")
    service, _ = _service(
        state_repository=state_repository,
        broker=broker,
    )
    for index, name in enumerate(("first-timeout", "second-timeout")):
        plan = _plan(name, 1, target=150.0 + index * 0.1)
        service.slots[index] = service.position_service.prepare(
            __import__(
                "ogami_oanda.domain.positions.managed_position",
                fromlist=["ManagedPosition"],
            ).ManagedPosition.registered(name, "USD_JPY"),
            plan,
        ).pending(f"order-{index + 1}").with_runtime(
            registered_at=datetime(2026, 1, 2, 0, 0, 0),
        )
        broker.orders[f"order-{index + 1}"] = PositionSnapshot(
            name,
            "USD_JPY",
            OrderState.PENDING,
            TradeState.NONE,
            order_id=f"order-{index + 1}",
            life=True,
        )
    service.position_service.clock.value = datetime(2026, 1, 2, 0, 31, 0)

    service.sync_all(current_price=150.2, dry_run=False)

    assert trace.count(("broker", "cancel_order")) == 1
    assert service.pending_mutations[0].broker_reference_id == "order-1"


@pytest.mark.contract
def test_unknown_startup_cancel_stops_remaining_orders():
    trace = []
    state_repository = _StateRepository(trace=trace)
    broker = _TracingBroker(trace, unknown_action="cancel_order")
    service, _ = _service(
        state_repository=state_repository,
        broker=broker,
    )
    for order_id in ("startup-1", "startup-2"):
        broker.orders[order_id] = PositionSnapshot(
            order_id,
            "USD_JPY",
            OrderState.PENDING,
            TradeState.NONE,
            order_id=order_id,
            life=True,
        )

    assert service.cancel_pending_on_start(True) == ()

    assert trace.count(("broker", "cancel_order")) == 1
    assert service.pending_mutations[0].broker_reference_id == "startup-1"


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
    state_repository = _StateRepository()
    service, broker = _service(state_repository=state_repository)
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
    checkpoint = state_repository.saved[-1]
    assert checkpoint.pending_mutations == ()
    assert checkpoint.slots[1] is not None
    assert checkpoint.slots[1].snapshot.order_state is OrderState.CANCELLED
    journal_index = next(
        index
        for index, item in enumerate(state_repository.saved)
        if item.pending_mutations
        and item.pending_mutations[0].action == "cancel_order"
    )
    assert not any(
        not item.pending_mutations
        and item.slots[1] is not None
        and item.slots[1].snapshot.order_state is OrderState.PENDING
        for item in state_repository.saved[journal_index + 1 :]
    )
