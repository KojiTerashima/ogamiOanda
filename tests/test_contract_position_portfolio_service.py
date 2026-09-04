from datetime import datetime

import pytest

from ogami_oanda.application.ports.broker import (
    BrokerTradeClosure,
    BrokerTransaction,
    BrokerTransactionBatch,
    ExecutionResult,
    MutationState,
    OrderSubmissionResult,
)
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
from ogami_oanda.domain.positions.managed_position import ManagedPosition
from ogami_oanda.strategy.contracts import StrategyCommand, StrategyCommandAction
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


@pytest.mark.contract
def test_runtime_missing_trade_recovers_from_closed_trade_transaction_once():
    state_repository = _StateRepository()
    broker = FakeBroker()
    broker.transactions = BrokerTransactionBatch(
        (
            BrokerTransaction(
                "202",
                "ORDER_FILL",
                order_id="close-order",
                pair="USD_JPY",
                units=-1000,
                price=149.9,
                reason="STOP_LOSS_ORDER",
                occurred_at=datetime(2026, 1, 2, 0, 4, 0),
                closed_trades=(
                    BrokerTradeClosure(
                        "trade-1",
                        1000,
                        149.9,
                        -100.0,
                        "STOP_LOSS_ORDER",
                        datetime(2026, 1, 2, 0, 4, 0),
                    ),
                ),
            ),
        ),
        "202",
    )
    service, _ = _service(
        state_repository=state_repository,
        broker=broker,
    )
    service.transaction_cursor = "200"
    service.slots[0] = (
        ManagedPosition.registered("missing-trade", "USD_JPY")
        .with_order_plan(_plan("missing-trade", 1), datetime(2026, 1, 2))
        .pending("order-1")
        .filled("trade-1", datetime(2026, 1, 2, 0, 1, 0))
        ._replace(
            direction=1,
            target_price=150.0,
            units=1000,
        )
    )

    first = service.sync_all(current_price=149.9)
    second = service.sync_all(current_price=149.9)

    assert service.startup_state is PortfolioStartupState.READY
    assert service.slots[0] is not None
    assert service.slots[0].snapshot.trade_state is TradeState.CLOSED
    assert service.slots[0].snapshot.life is False
    assert service.slots[0].snapshot.realized_pl == -100.0
    assert service.slots[0].snapshot.average_close_price == 149.9
    assert service.slots[0].snapshot.close_reason == "STOP_LOSS_ORDER"
    assert service.transaction_cursor == "202"
    assert [event.kind for event in first.close_events] == ["trade_closed"]
    assert second.close_events == ()
    assert len(service.position_service.history.records) == 1
    assert state_repository.saved[-1].slots[0].snapshot.trade_state is TradeState.CLOSED


@pytest.mark.contract
def test_runtime_missing_trade_without_close_evidence_quarantines_and_blocks_orders():
    state_repository = _StateRepository()
    broker = FakeBroker()
    broker.transactions = BrokerTransactionBatch((), "202")
    service, _ = _service(
        state_repository=state_repository,
        broker=broker,
    )
    service.transaction_cursor = "200"
    service.slots[0] = (
        ManagedPosition.registered("missing-trade", "USD_JPY")
        .with_order_plan(_plan("missing-trade", 1), datetime(2026, 1, 2))
        .pending("order-1")
        .filled("trade-1", datetime(2026, 1, 2, 0, 1, 0))
        ._replace(direction=1, target_price=150.0, units=1000)
    )

    summary = service.sync_all(current_price=149.9)
    registration = service.register_plans([_plan("blocked", 1)], submit=True)

    assert service.startup_state is PortfolioStartupState.QUARANTINED
    assert service.slots[0] is not None
    assert service.slots[0].snapshot.trade_state is TradeState.OPEN
    assert service.slots[0].snapshot.life is True
    assert summary.open == 1
    assert registration.rejected == (("blocked", "portfolio_quarantined"),)
    assert broker.requests == []
    assert broker.commands == []
    assert state_repository.saved[-1].slots[0].snapshot.trade_state is TradeState.OPEN
    assert len(service.position_service.notifier.messages) == 1
    message, category, pair = service.position_service.notifier.messages[0]
    assert "trade-1" not in message
    assert (category, pair) == ("live", "USD_JPY")


@pytest.mark.contract
def test_runtime_missing_trade_with_incomplete_close_evidence_quarantines():
    state_repository = _StateRepository()
    broker = FakeBroker()
    broker.transactions = BrokerTransactionBatch(
        (
            BrokerTransaction(
                "202",
                "ORDER_FILL",
                order_id="close-order",
                pair="USD_JPY",
                units=-1000,
                price=149.9,
                reason="STOP_LOSS_ORDER",
                occurred_at=datetime(2026, 1, 2, 0, 4, 0),
                closed_trades=(
                    BrokerTradeClosure(
                        "trade-1",
                        1000,
                        149.9,
                        None,
                        "STOP_LOSS_ORDER",
                        datetime(2026, 1, 2, 0, 4, 0),
                    ),
                ),
            ),
        ),
        "202",
    )
    service, _ = _service(
        state_repository=state_repository,
        broker=broker,
    )
    service.transaction_cursor = "200"
    service.slots[0] = (
        ManagedPosition.registered("missing-trade", "USD_JPY")
        .with_order_plan(_plan("missing-trade", 1), datetime(2026, 1, 2))
        .pending("order-1")
        .filled("trade-1", datetime(2026, 1, 2, 0, 1, 0))
        ._replace(direction=1, target_price=150.0, units=1000)
    )

    try:
        service.sync_all(current_price=149.9)
    except TypeError as error:
        pytest.fail(f"incomplete close evidence escaped quarantine: {error}")

    assert service.startup_state is PortfolioStartupState.QUARANTINED
    assert service.slots[0] is not None
    assert service.slots[0].snapshot.trade_state is TradeState.OPEN
    assert service.position_service.history.records == []


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
            self.commands.append(("cancel_order", (order_id,)))
            return ExecutionResult(
                False,
                message="cancel outcome unknown",
                state=MutationState.UNKNOWN,
            )
        return super().cancel_order(order_id)

    def close_trade(self, trade_id, units=None):
        self.trace.append(("broker", "close_trade"))
        if self.unknown_action == "close_trade":
            self.commands.append(("close_trade", (trade_id, units)))
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


@pytest.mark.contract
def test_strategy_commands_are_source_scoped_and_reduce_oldest_then_partial():
    service, broker = _service()
    first = (
        ManagedPosition.registered("first", "USD_JPY")
        .with_order_plan(_plan("first", 1), datetime(2026, 1, 2, 0, 0, 0))
        .filled("trade-first", datetime(2026, 1, 2, 0, 1, 0))
    )
    second = (
        ManagedPosition.registered("second", "USD_JPY")
        .with_order_plan(_plan("second", 1), datetime(2026, 1, 2, 0, 0, 0))
        .filled("trade-second", datetime(2026, 1, 2, 0, 2, 0))
    )
    other = (
        ManagedPosition.registered("other", "USD_JPY")
        .with_order_plan(_plan("other", 1, source="other"), datetime(2026, 1, 2, 0, 0, 0))
        .filled("trade-other", datetime(2026, 1, 2, 0, 0, 0))
    )
    service.slots[:3] = [
        first.with_runtime(source="matcha_oanda")._replace(units=100),
        second.with_runtime(source="matcha_oanda")._replace(units=150),
        other,
    ]

    result = service.execute_strategy_commands(
        (StrategyCommand(StrategyCommandAction.REDUCE_EXPOSURE, "matcha_oanda", "reduce", 200),)
    )

    assert result.allows_intents
    assert [(item.action, item.reference_id, item.data["units"]) for item in result.executed] == [
        ("reduce_trade", "trade-first", 100),
        ("reduce_trade", "trade-second", 100),
    ]
    assert broker.commands == [
        ("close_trade", ("trade-first", 100)),
        ("close_trade", ("trade-second", 100)),
    ]
    assert service.slots[2] == other


@pytest.mark.contract
def test_strategy_command_dry_run_is_observational():
    service, broker = _service()
    position = (
        ManagedPosition.registered("dry", "USD_JPY")
        .with_order_plan(_plan("dry", 1), datetime(2026, 1, 2, 0, 0, 0))
        .pending("order-dry")
        .with_runtime(source="matcha_oanda")
    )
    service.slots[0] = position
    before_slots = tuple(service.slots)
    before_pending = service.pending_mutations

    result = service.execute_strategy_commands(
        (StrategyCommand(StrategyCommandAction.CANCEL_PENDING, "matcha_oanda", "cancel"),),
        dry_run=True,
    )

    assert result.allows_intents
    assert [item.reference_id for item in result.executed] == ["order-dry"]
    assert tuple(service.slots) == before_slots
    assert service.pending_mutations == before_pending
    assert broker.commands == []


@pytest.mark.contract
def test_strategy_commands_cancel_pending_and_close_all_in_stable_slot_order():
    service, broker = _service()
    service.slots[:6] = [
        (
            ManagedPosition.registered("pending-1", "USD_JPY")
            .with_order_plan(_plan("pending-1", 1), datetime(2026, 1, 2, 0, 0, 0))
            .pending("order-1")
            .with_runtime(source="matcha_oanda")
        ),
        (
            ManagedPosition.registered("open-1", "USD_JPY")
            .with_order_plan(_plan("open-1", 1), datetime(2026, 1, 2, 0, 0, 0))
            .filled("trade-1", datetime(2026, 1, 2, 0, 1, 0))
            .with_runtime(source="matcha_oanda")
        ),
        (
            ManagedPosition.registered("pending-other", "USD_JPY")
            .with_order_plan(
                _plan("pending-other", 1, source="other"),
                datetime(2026, 1, 2, 0, 0, 0),
            )
            .pending("order-other")
            .with_runtime(source="other")
        ),
        (
            ManagedPosition.registered("open-2", "USD_JPY")
            .with_order_plan(_plan("open-2", 1), datetime(2026, 1, 2, 0, 0, 0))
            .filled("trade-2", datetime(2026, 1, 2, 0, 2, 0))
            .with_runtime(source="matcha_oanda")
        ),
        (
            ManagedPosition.registered("pending-2", "USD_JPY")
            .with_order_plan(
                _plan("pending-2", 1),
                datetime(2026, 1, 2, 0, 0, 0),
            )
            .pending("order-2")
            .with_runtime(source="matcha_oanda")
        ),
        (
            ManagedPosition.registered("open-other", "USD_JPY")
            .with_order_plan(
                _plan("open-other", 1, source="other"),
                datetime(2026, 1, 2, 0, 0, 0),
            )
            .filled("trade-other", datetime(2026, 1, 2, 0, 0, 0))
            .with_runtime(source="other")
        ),
    ]

    result = service.execute_strategy_commands(
        (
            StrategyCommand(
                StrategyCommandAction.CANCEL_PENDING,
                "matcha_oanda",
                "cancel",
            ),
            StrategyCommand(
                StrategyCommandAction.CLOSE_ALL,
                "matcha_oanda",
                "close",
            ),
        )
    )

    assert result.allows_intents
    assert [
        (item.action, item.reference_id, item.reason)
        for item in result.executed
    ] == [
        ("cancel_order", "order-1", "cancel"),
        ("cancel_order", "order-2", "cancel"),
        ("close_trade", "trade-1", "close"),
        ("close_trade", "trade-2", "close"),
    ]
    assert broker.commands == [
        ("cancel_order", ("order-1",)),
        ("cancel_order", ("order-2",)),
        ("close_trade", ("trade-1", None)),
        ("close_trade", ("trade-2", None)),
    ]
    assert service.slots[0].snapshot.order_state is OrderState.CANCELLED
    assert service.slots[1].snapshot.trade_state is TradeState.CLOSED
    assert service.slots[2].snapshot.order_state is OrderState.PENDING
    assert service.slots[3].snapshot.trade_state is TradeState.CLOSED
    assert service.slots[4].snapshot.order_state is OrderState.CANCELLED
    assert service.slots[5].snapshot.trade_state is TradeState.OPEN


@pytest.mark.contract
def test_strategy_reduce_exposure_tiebreaks_equal_fill_times_by_slot_and_updates_remaining_units():
    service, broker = _service()
    filled_at = datetime(2026, 1, 2, 0, 1, 0)
    later_slot = (
        ManagedPosition.registered("later-slot", "USD_JPY")
        .with_order_plan(_plan("later-slot", 1), datetime(2026, 1, 2, 0, 0, 0))
        .filled("trade-later", filled_at)
        .with_runtime(source="matcha_oanda")
        ._replace(units=120)
    )
    earlier_slot = (
        ManagedPosition.registered("earlier-slot", "USD_JPY")
        .with_order_plan(_plan("earlier-slot", 1), datetime(2026, 1, 2, 0, 0, 0))
        .filled("trade-earlier", filled_at)
        .with_runtime(source="matcha_oanda")
        ._replace(units=120)
    )
    service.slots[1] = later_slot
    service.slots[0] = earlier_slot

    result = service.execute_strategy_commands(
        (
            StrategyCommand(
                StrategyCommandAction.REDUCE_EXPOSURE,
                "matcha_oanda",
                "reduce",
                150,
            ),
        )
    )

    assert result.allows_intents
    assert [
        (item.reference_id, item.data["units"])
        for item in result.executed
    ] == [
        ("trade-earlier", 120),
        ("trade-later", 30),
    ]
    assert broker.commands == [
        ("close_trade", ("trade-earlier", 120)),
        ("close_trade", ("trade-later", 30)),
    ]
    assert service.slots[0].snapshot.trade_state is TradeState.CLOSED
    assert service.slots[1].snapshot.units == 90


@pytest.mark.contract
def test_strategy_reduce_rejects_before_mutation_when_source_has_no_exposure():
    service, broker = _service()
    service.slots[0] = (
        ManagedPosition.registered("other", "USD_JPY")
        .with_order_plan(
            _plan("other", 1, source="other"),
            datetime(2026, 1, 2, 0, 0, 0),
        )
        .filled("trade-other", datetime(2026, 1, 2, 0, 1, 0))
        .with_runtime(source="other")
        ._replace(units=100)
    )
    before_slots = tuple(service.slots)

    result = service.execute_strategy_commands(
        (
            StrategyCommand(
                StrategyCommandAction.REDUCE_EXPOSURE,
                "matcha_oanda",
                "reduce",
                50,
            ),
        )
    )

    assert result.allows_intents is False
    assert result.rejected == ("insufficient_source_exposure",)
    assert result.executed == ()
    assert broker.commands == []
    assert service.pending_mutations == ()
    assert tuple(service.slots) == before_slots


@pytest.mark.contract
def test_strategy_reduce_rejects_before_mutation_when_source_exposure_is_partial():
    service, broker = _service()
    service.slots[0] = (
        ManagedPosition.registered("partial", "USD_JPY")
        .with_order_plan(
            _plan("partial", 1),
            datetime(2026, 1, 2, 0, 0, 0),
        )
        .filled("trade-partial", datetime(2026, 1, 2, 0, 1, 0))
        .with_runtime(source="matcha_oanda")
        ._replace(units=100)
    )
    before_slots = tuple(service.slots)

    result = service.execute_strategy_commands(
        (
            StrategyCommand(
                StrategyCommandAction.REDUCE_EXPOSURE,
                "matcha_oanda",
                "reduce",
                150,
            ),
        )
    )

    assert result.allows_intents is False
    assert result.rejected == ("insufficient_source_exposure",)
    assert result.executed == ()
    assert broker.commands == []
    assert service.pending_mutations == ()
    assert tuple(service.slots) == before_slots


@pytest.mark.contract
def test_strategy_reduce_shortfall_preserves_earlier_command_result_and_state():
    service, broker = _service()
    service.slots[:2] = [
        (
            ManagedPosition.registered("pending", "USD_JPY")
            .with_order_plan(
                _plan("pending", 1),
                datetime(2026, 1, 2, 0, 0, 0),
            )
            .pending("order-pending")
            .with_runtime(source="matcha_oanda")
        ),
        (
            ManagedPosition.registered("partial", "USD_JPY")
            .with_order_plan(
                _plan("partial", 1),
                datetime(2026, 1, 2, 0, 0, 0),
            )
            .filled("trade-partial", datetime(2026, 1, 2, 0, 1, 0))
            .with_runtime(source="matcha_oanda")
            ._replace(units=100)
        ),
    ]

    result = service.execute_strategy_commands(
        (
            StrategyCommand(
                StrategyCommandAction.CANCEL_PENDING,
                "matcha_oanda",
                "cancel",
            ),
            StrategyCommand(
                StrategyCommandAction.REDUCE_EXPOSURE,
                "matcha_oanda",
                "reduce",
                150,
            ),
        )
    )

    assert result.allows_intents is False
    assert result.rejected == ("insufficient_source_exposure",)
    assert [item.reference_id for item in result.executed] == ["order-pending"]
    assert broker.commands == [("cancel_order", ("order-pending",))]
    assert service.slots[0].snapshot.order_state is OrderState.CANCELLED
    assert service.slots[1].snapshot.trade_state is TradeState.OPEN
    assert service.slots[1].snapshot.units == 100
    assert service.pending_mutations == ()


@pytest.mark.contract
def test_strategy_command_rejection_stops_remaining_commands_and_forbids_intents():
    class _RejectingBroker(FakeBroker):
        def cancel_order(self, order_id):
            self.commands.append(("cancel_order", (order_id,)))
            return ExecutionResult(False, reference_id=order_id, message="rejected")

    service, broker = _service(broker=_RejectingBroker())
    service.slots[:2] = [
        (
            ManagedPosition.registered("pending", "USD_JPY")
            .with_order_plan(_plan("pending", 1), datetime(2026, 1, 2, 0, 0, 0))
            .pending("order-1")
            .with_runtime(source="matcha_oanda")
        ),
        (
            ManagedPosition.registered("open", "USD_JPY")
            .with_order_plan(_plan("open", 1), datetime(2026, 1, 2, 0, 0, 0))
            .filled("trade-1", datetime(2026, 1, 2, 0, 1, 0))
            .with_runtime(source="matcha_oanda")
        ),
    ]

    result = service.execute_strategy_commands(
        (
            StrategyCommand(
                StrategyCommandAction.CANCEL_PENDING,
                "matcha_oanda",
                "cancel",
            ),
            StrategyCommand(
                StrategyCommandAction.CLOSE_ALL,
                "matcha_oanda",
                "close",
            ),
        )
    )

    assert result.allows_intents is False
    assert result.rejected == ("rejected",)
    assert [item.reference_id for item in result.executed] == ["order-1"]
    assert broker.commands == [("cancel_order", ("order-1",))]
    assert service.slots[0].snapshot.order_state is OrderState.PENDING
    assert service.slots[1].snapshot.trade_state is TradeState.OPEN


@pytest.mark.contract
def test_strategy_command_unknown_reduction_stops_batch_and_journals_exact_units():
    trace = []
    state_repository = _StateRepository(trace=trace)
    broker = _TracingBroker(trace, unknown_action="close_trade")
    service, _ = _service(state_repository=state_repository, broker=broker)
    service.slots[:2] = [
        (
            ManagedPosition.registered("reduce-me", "USD_JPY")
            .with_order_plan(
                _plan("reduce-me", 1),
                datetime(2026, 1, 2, 0, 0, 0),
            )
            .filled("trade-reduce", datetime(2026, 1, 2, 0, 1, 0))
            .with_runtime(source="matcha_oanda", direction=1)
            ._replace(units=120)
        ),
        (
            ManagedPosition.registered("later", "USD_JPY")
            .with_order_plan(_plan("later", 1), datetime(2026, 1, 2, 0, 0, 0))
            .filled("trade-later", datetime(2026, 1, 2, 0, 2, 0))
            .with_runtime(source="matcha_oanda")
            ._replace(units=50)
        ),
    ]

    result = service.execute_strategy_commands(
        (
            StrategyCommand(
                StrategyCommandAction.REDUCE_EXPOSURE,
                "matcha_oanda",
                "reduce",
                70,
            ),
            StrategyCommand(
                StrategyCommandAction.CLOSE_ALL,
                "matcha_oanda",
                "close",
            ),
        )
    )

    assert result.allows_intents is False
    assert result.unresolved is True
    assert [item.reference_id for item in result.executed] == ["trade-reduce"]
    assert broker.commands == [("close_trade", ("trade-reduce", 70))]
    assert service.pending_mutations[0].action == "reduce_trade"
    assert service.pending_mutations[0].requested_units == 70
    assert service.pending_mutations[0].original_units == 120
    assert service.pending_mutations[0].direction == 1
    assert state_repository.saved[-1].pending_mutations[0].requested_units == 70
    assert state_repository.saved[-1].pending_mutations[0].original_units == 120
    broker_index = trace.index(("broker", "close_trade"))
    assert (
        "save",
        ("reduce_trade",),
    ) in trace[:broker_index]
    assert service.slots[0].snapshot.units == 120
    assert service.slots[1].snapshot.trade_state is TradeState.OPEN


@pytest.mark.contract
def test_strategy_command_dry_run_does_not_save_repository():
    state_repository = _StateRepository()
    service, broker = _service(state_repository=state_repository)
    service.slots[0] = (
        ManagedPosition.registered("dry-repo", "USD_JPY")
        .with_order_plan(_plan("dry-repo", 1), datetime(2026, 1, 2, 0, 0, 0))
        .pending("order-dry")
        .with_runtime(source="matcha_oanda")
    )
    saved_before = len(state_repository.saved)

    result = service.execute_strategy_commands(
        (
            StrategyCommand(
                StrategyCommandAction.CANCEL_PENDING,
                "matcha_oanda",
                "cancel",
            ),
        ),
        dry_run=True,
    )

    assert result.allows_intents
    assert len(state_repository.saved) == saved_before
    assert broker.commands == []


@pytest.mark.contract
def test_strategy_reduce_dry_run_reports_full_then_partial_without_mutation():
    state_repository = _StateRepository()
    service, broker = _service(state_repository=state_repository)
    service.slots[:2] = [
        (
            ManagedPosition.registered("dry-first", "USD_JPY")
            .with_order_plan(
                _plan("dry-first", 1),
                datetime(2026, 1, 2, 0, 0, 0),
            )
            .filled("trade-dry-first", datetime(2026, 1, 2, 0, 1, 0))
            .with_runtime(source="matcha_oanda")
            ._replace(units=100)
        ),
        (
            ManagedPosition.registered("dry-second", "USD_JPY")
            .with_order_plan(
                _plan("dry-second", 1),
                datetime(2026, 1, 2, 0, 0, 0),
            )
            .filled("trade-dry-second", datetime(2026, 1, 2, 0, 2, 0))
            .with_runtime(source="matcha_oanda")
            ._replace(units=100)
        ),
    ]
    before_slots = tuple(service.slots)
    saved_before = len(state_repository.saved)

    result = service.execute_strategy_commands(
        (
            StrategyCommand(
                StrategyCommandAction.REDUCE_EXPOSURE,
                "matcha_oanda",
                "dry-reduce",
                150,
            ),
        ),
        dry_run=True,
    )

    assert [
        (item.reference_id, item.data["units"])
        for item in result.executed
    ] == [
        ("trade-dry-first", 100),
        ("trade-dry-second", 50),
    ]
    assert tuple(service.slots) == before_slots
    assert service.pending_mutations == ()
    assert len(state_repository.saved) == saved_before
    assert broker.commands == []


@pytest.mark.contract
def test_strategy_command_later_rejection_keeps_prior_confirmation_and_stops():
    class _RejectSecondCloseBroker(FakeBroker):
        def close_trade(self, trade_id, units=None):
            self.commands.append(("close_trade", (trade_id, units)))
            if len(self.commands) == 2:
                return ExecutionResult(
                    False,
                    reference_id=trade_id,
                    message="second rejected",
                )
            return ExecutionResult(True, reference_id=trade_id)

    state_repository = _StateRepository()
    broker = _RejectSecondCloseBroker()
    service, _ = _service(
        state_repository=state_repository,
        broker=broker,
    )
    for index in range(3):
        service.slots[index] = (
            ManagedPosition.registered(f"close-{index}", "USD_JPY")
            .with_order_plan(
                _plan(f"close-{index}", 1),
                datetime(2026, 1, 2, 0, 0, 0),
            )
            .filled(
                f"trade-close-{index}",
                datetime(2026, 1, 2, 0, index + 1, 0),
            )
            .with_runtime(source="matcha_oanda")
            ._replace(units=100)
        )

    result = service.execute_strategy_commands(
        (
            StrategyCommand(
                StrategyCommandAction.CLOSE_ALL,
                "matcha_oanda",
                "close",
            ),
        )
    )

    assert result.allows_intents is False
    assert result.rejected == ("second rejected",)
    assert [item.reference_id for item in result.executed] == [
        "trade-close-0",
        "trade-close-1",
    ]
    assert broker.commands == [
        ("close_trade", ("trade-close-0", None)),
        ("close_trade", ("trade-close-1", None)),
    ]
    assert service.slots[0].snapshot.trade_state is TradeState.CLOSED
    assert service.slots[0].snapshot.units == 0
    assert service.slots[1].snapshot.trade_state is TradeState.OPEN
    assert service.slots[2].snapshot.trade_state is TradeState.OPEN
    assert service.pending_mutations == ()
    assert state_repository.saved[-1].pending_mutations == ()
