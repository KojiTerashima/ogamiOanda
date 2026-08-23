from __future__ import annotations

from dataclasses import replace
from datetime import datetime

import pytest

from ogami_oanda.application.ports.broker import (
    BrokerTransaction,
    BrokerTransactionBatch,
    ExecutionResult,
    MutationState,
    OrderSubmissionResult,
)
from ogami_oanda.application.ports.position_state import (
    CheckpointLoadResult,
    CheckpointLoadStatus,
    PendingBrokerMutation,
    PortfolioAnalyticsState,
    PositionStateCheckpoint,
    account_identity_hash,
)
from ogami_oanda.application.services.order_planner import OrderPlanner
from ogami_oanda.application.services.position_portfolio_service import (
    PortfolioStartupState,
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
    SubmissionPhase,
    TradeState,
)
from tests.fakes import (
    FakeBroker,
    FakeNotifier,
    FixedClock,
    InMemoryTradeHistoryRepository,
)


class _StateRepository:
    def __init__(self, result):
        self.result = result
        self.saved = []

    def load(self, **_kwargs):
        return self.result

    def save(self, checkpoint):
        self.saved.append(checkpoint)


def _plan(
    name="restored",
    *,
    target=150.0,
    order_type=OrderType.LIMIT,
):
    return OrderPlanner().plan(
        OrderIntent(
            "USD_JPY",
            Direction.BUY,
            order_type,
            target,
            order_type is not OrderType.MARKET,
            0.2,
            False,
            0.1,
            False,
            100,
            name,
            1,
            30,
            lc_change=(
                {"exe": True, "trigger": 0.03, "ensure": 0.01, "time_after": 0},
            ),
            metadata={"source": "line", "line_strategy": "recovery"},
        ),
        OrderContext(149.9, "2026/01/02 10:00:00"),
    )


def _service(repository, broker, *, state_writable=True):
    clock = FixedClock(datetime(2026, 1, 2, 10, 5, 0))
    position_service = PositionService(
        broker,
        broker,
        FakeNotifier(),
        InMemoryTradeHistoryRepository(),
        clock,
    )
    return PositionPortfolioService(
        "USD_JPY",
        position_service,
        broker,
        broker,
        state_repository=repository,
        account_hash=account_identity_hash("id"),
        state_writable=state_writable,
    )


def _checkpoint(position, *, mutation=(), cursor="100"):
    return PositionStateCheckpoint(
        account_hash=account_identity_hash("id"),
        pair="USD_JPY",
        slots=(position,) + (None,) * 14,
        transaction_cursor=cursor,
        pending_mutations=mutation,
        emitted_event_ids=frozenset({"trade_opened:trade-1"}),
        reported_event_ids=frozenset({"trade_closed:trade-old"}),
        analytics=PortfolioAnalyticsState(
            total_yen=50,
            total_yen_max=50,
            total_yen_min=-10,
            total_pips=5,
            total_pips_max=5,
            total_pips_min=-1,
            plus_yen_position_num=1,
            before_latest_name="trade-old",
            history_plus_minus=(0, 5),
            history_names=("0", "trade-old"),
            result_dic_arr=(
                {
                    "name": "trade-old",
                    "pair": "USD_JPY",
                    "res": "50",
                    "pl_per_units": 5,
                },
            ),
        ),
    )


@pytest.mark.contract
def test_startup_reconciliation_restores_full_open_runtime_and_reporting_state():
    plan = _plan()
    persisted = (
        ManagedPosition.registered("restored", "USD_JPY")
        .with_order_plan(plan, datetime(2026, 1, 2, 10, 0, 0))
        .pending("order-1")
        .filled("trade-1", datetime(2026, 1, 2, 10, 1, 0))
        .with_runtime(
            applied_lc_change_index=0,
            linkage_id="link-1",
            max_unrealized_pl=12,
        )
    )
    repository = _StateRepository(
        CheckpointLoadResult(
            CheckpointLoadStatus.LOADED,
            _checkpoint(persisted),
        )
    )
    broker = FakeBroker()
    broker.positions["trade-1"] = PositionSnapshot(
        "restored",
        "USD_JPY",
        OrderState.FILLED,
        TradeState.OPEN,
        order_id="order-1",
        trade_id="trade-1",
        life=True,
        direction=1,
        target_price=150.0,
        current_stop_loss=149.9,
    )
    service = _service(repository, broker)

    result = service.restore_and_reconcile()

    assert result.state is PortfolioStartupState.READY
    restored = service.slots[0]
    assert restored is not None
    assert restored.runtime.order_plan == plan
    assert restored.runtime.applied_lc_change_index == 0
    assert restored.runtime.linkage_id == "link-1"
    assert service.position_service._emitted_event_ids == {"trade_opened:trade-1"}
    reporting = service.position_service.closure_reporting
    assert reporting._reported_event_ids == {"trade_closed:trade-old"}
    assert reporting.analytics.total_yen == 50
    assert reporting.analytics.before_latest_name == "trade-old"


@pytest.mark.contract
def test_startup_reconciliation_resolves_uncertain_market_fill_from_transactions():
    plan = _plan("uncertain", order_type=OrderType.MARKET)
    persisted = (
        ManagedPosition.registered("uncertain", "USD_JPY")
        .with_order_plan(plan, datetime(2026, 1, 2, 10, 0, 0))
        .submission_uncertain("timeout")
        .with_runtime(submission_phase=SubmissionPhase.SUBMITTING)
    )
    mutation = PendingBrokerMutation(
        "submit_order",
        "uncertain",
        plan.broker_request.client_reference,
    )
    repository = _StateRepository(
        CheckpointLoadResult(
            CheckpointLoadStatus.LOADED,
            _checkpoint(persisted, mutation=(mutation,)),
        )
    )
    broker = FakeBroker()
    broker.transactions = BrokerTransactionBatch(
        (
            BrokerTransaction(
                "101",
                "MARKET_ORDER",
                order_id="101",
                client_reference=plan.broker_request.client_reference,
                pair="USD_JPY",
                units=100,
                price=150.0,
            ),
            BrokerTransaction(
                "102",
                "ORDER_FILL",
                order_id="101",
                trade_id="trade-1",
                pair="USD_JPY",
                units=100,
                price=150.01,
                occurred_at=datetime(2026, 1, 2, 10, 0, 1),
            ),
        ),
        "102",
    )
    broker.positions["trade-1"] = PositionSnapshot(
        "uncertain",
        "USD_JPY",
        OrderState.FILLED,
        TradeState.OPEN,
        order_id="101",
        trade_id="trade-1",
        life=True,
        direction=1,
        target_price=150.01,
    )
    service = _service(repository, broker)

    result = service.restore_and_reconcile()

    assert result.state is PortfolioStartupState.READY
    assert service.slots[0] is not None
    assert service.slots[0].snapshot.trade_id == "trade-1"
    assert service.slots[0].runtime.submission_phase is SubmissionPhase.FILLED
    assert service.pending_mutations == ()
    assert service.transaction_cursor == "102"


@pytest.mark.contract
def test_startup_reconciliation_resolves_market_fill_without_client_extensions():
    plan = _plan(
        "uncertain-no-client-id",
        order_type=OrderType.MARKET,
    )
    persisted = (
        ManagedPosition.registered("uncertain-no-client-id", "USD_JPY")
        .with_order_plan(plan, datetime(2026, 1, 2, 10, 0, 0))
        .submission_uncertain("timeout")
        .with_runtime(submission_phase=SubmissionPhase.SUBMITTING)
    )
    repository = _StateRepository(
        CheckpointLoadResult(
            CheckpointLoadStatus.LOADED,
            _checkpoint(
                persisted,
                mutation=(
                    PendingBrokerMutation(
                        "submit_order",
                        persisted.snapshot.name,
                        plan.broker_request.client_reference,
                    ),
                ),
            ),
        )
    )
    broker = FakeBroker()
    broker.transactions = BrokerTransactionBatch(
        (
            BrokerTransaction(
                "101",
                "MARKET_ORDER",
                order_id="101",
                pair="USD_JPY",
                units=100,
                price=150.0,
                occurred_at=datetime(2026, 1, 2, 10, 0, 1),
            ),
            BrokerTransaction(
                "102",
                "ORDER_FILL",
                order_id="101",
                trade_id="trade-1",
                pair="USD_JPY",
                units=100,
                price=150.01,
                occurred_at=datetime(2026, 1, 2, 10, 0, 1),
            ),
        ),
        "102",
    )
    broker.positions["trade-1"] = PositionSnapshot(
        persisted.snapshot.name,
        "USD_JPY",
        OrderState.FILLED,
        TradeState.OPEN,
        order_id="101",
        trade_id="trade-1",
        life=True,
        direction=1,
        target_price=150.01,
    )
    service = _service(repository, broker)

    result = service.restore_and_reconcile()

    assert result.state is PortfolioStartupState.READY
    assert service.slots[0] is not None
    assert service.slots[0].snapshot.trade_id == "trade-1"
    assert service.pending_mutations == ()


@pytest.mark.contract
def test_startup_reconciliation_resolves_uncertain_pending_order():
    plan = _plan("uncertain-pending")
    persisted = (
        ManagedPosition.registered("uncertain-pending", "USD_JPY")
        .with_order_plan(plan, datetime(2026, 1, 2, 10, 0, 0))
        .submission_uncertain("timeout")
        .with_runtime(submission_phase=SubmissionPhase.SUBMITTING)
    )
    repository = _StateRepository(
        CheckpointLoadResult(
            CheckpointLoadStatus.LOADED,
            _checkpoint(
                persisted,
                mutation=(
                    PendingBrokerMutation(
                        "submit_order",
                        persisted.snapshot.name,
                        plan.broker_request.client_reference,
                    ),
                ),
            ),
        )
    )
    broker = FakeBroker()
    broker.transactions = BrokerTransactionBatch(
        (
            BrokerTransaction(
                "101",
                "LIMIT_ORDER",
                order_id="101",
                pair="USD_JPY",
                units=100,
                price=150.0,
                occurred_at=datetime(2026, 1, 2, 10, 0, 1),
            ),
        ),
        "101",
    )
    broker.orders["101"] = PositionSnapshot(
        persisted.snapshot.name,
        "USD_JPY",
        OrderState.PENDING,
        TradeState.NONE,
        order_id="101",
        life=True,
        direction=1,
        target_price=150.0,
    )
    service = _service(repository, broker)

    result = service.restore_and_reconcile()

    assert result.state is PortfolioStartupState.READY
    assert service.slots[0] is not None
    assert service.slots[0].snapshot.order_id == "101"
    assert service.slots[0].runtime.submission_phase is SubmissionPhase.PENDING
    assert service.pending_mutations == ()


@pytest.mark.contract
def test_startup_reconciliation_does_not_match_stale_shape_only_transaction():
    plan = _plan("stale-shape")
    prepared_at = datetime(2026, 1, 2, 10, 0, 0)
    persisted = (
        ManagedPosition.registered(plan.intent.name, "USD_JPY")
        .with_order_plan(plan, prepared_at)
        .submission_uncertain("timeout")
    )
    repository = _StateRepository(
        CheckpointLoadResult(
            CheckpointLoadStatus.LOADED,
            _checkpoint(
                persisted,
                mutation=(
                    PendingBrokerMutation(
                        "submit_order",
                        persisted.snapshot.name,
                        plan.broker_request.client_reference,
                        prepared_at=prepared_at,
                    ),
                ),
            ),
        )
    )
    broker = FakeBroker()
    broker.transactions = BrokerTransactionBatch(
        (
            BrokerTransaction(
                "201",
                "LIMIT_ORDER",
                order_id="unrelated-order",
                pair="USD_JPY",
                units=100,
                price=150.0,
                occurred_at=datetime(2026, 1, 2, 10, 10, 0),
            ),
        ),
        "201",
    )
    service = _service(repository, broker)

    result = service.restore_and_reconcile()

    assert result.state is PortfolioStartupState.RECONCILING
    assert service.pending_mutations
    assert service.slots[0] is not None
    assert service.slots[0].snapshot.order_id is None


@pytest.mark.contract
def test_startup_reconciliation_rejects_different_nonempty_client_reference():
    plan = _plan("different-reference")
    prepared_at = datetime(2026, 1, 2, 10, 0, 0)
    persisted = (
        ManagedPosition.registered(plan.intent.name, "USD_JPY")
        .with_order_plan(plan, prepared_at)
        .submission_uncertain("timeout")
    )
    repository = _StateRepository(
        CheckpointLoadResult(
            CheckpointLoadStatus.LOADED,
            _checkpoint(
                persisted,
                mutation=(
                    PendingBrokerMutation(
                        "submit_order",
                        persisted.snapshot.name,
                        plan.broker_request.client_reference,
                        prepared_at=prepared_at,
                    ),
                ),
            ),
        )
    )
    broker = FakeBroker()
    broker.transactions = BrokerTransactionBatch(
        (
            BrokerTransaction(
                "201",
                "LIMIT_ORDER",
                order_id="external-order",
                client_reference="external-client-reference",
                pair="USD_JPY",
                units=100,
                price=150.0,
                occurred_at=datetime(2026, 1, 2, 10, 0, 1),
            ),
        ),
        "201",
    )
    broker.orders["external-order"] = PositionSnapshot(
        "external",
        "USD_JPY",
        OrderState.PENDING,
        TradeState.NONE,
        order_id="external-order",
        life=True,
        direction=1,
        target_price=150.0,
        client_reference="external-client-reference",
    )
    service = _service(repository, broker)

    result = service.restore_and_reconcile()

    assert result.state is PortfolioStartupState.QUARANTINED
    assert service.pending_mutations
    assert service.slots[0] is not None
    assert service.slots[0].snapshot.order_id is None


@pytest.mark.contract
def test_startup_reconciliation_does_not_match_stale_direct_fill():
    plan = _plan("stale-fill")
    prepared_at = datetime(2026, 1, 2, 10, 0, 0)
    persisted = (
        ManagedPosition.registered(plan.intent.name, "USD_JPY")
        .with_order_plan(plan, prepared_at)
        .submission_uncertain("timeout")
    )
    repository = _StateRepository(
        CheckpointLoadResult(
            CheckpointLoadStatus.LOADED,
            _checkpoint(
                persisted,
                mutation=(
                    PendingBrokerMutation(
                        "submit_order",
                        persisted.snapshot.name,
                        plan.broker_request.client_reference,
                        prepared_at=prepared_at,
                    ),
                ),
            ),
        )
    )
    broker = FakeBroker()
    broker.transactions = BrokerTransactionBatch(
        (
            BrokerTransaction(
                "202",
                "ORDER_FILL",
                order_id="unrelated-order",
                trade_id="unrelated-trade",
                pair="USD_JPY",
                units=100,
                price=150.01,
                occurred_at=datetime(2026, 1, 2, 10, 10, 0),
            ),
        ),
        "202",
    )
    broker.positions["unrelated-trade"] = PositionSnapshot(
        "unrelated",
        "USD_JPY",
        OrderState.FILLED,
        TradeState.OPEN,
        order_id="unrelated-order",
        trade_id="unrelated-trade",
        life=True,
        direction=1,
        target_price=150.01,
    )
    service = _service(repository, broker)

    result = service.restore_and_reconcile()

    assert result.state is PortfolioStartupState.QUARANTINED
    assert service.pending_mutations
    assert service.slots[0] is not None
    assert service.slots[0].snapshot.trade_id is None


@pytest.mark.contract
def test_startup_reconciliation_does_not_match_standalone_direct_fill():
    plan = _plan("standalone-fill", order_type=OrderType.MARKET)
    prepared_at = datetime(2026, 1, 2, 10, 0, 0)
    persisted = (
        ManagedPosition.registered(plan.intent.name, "USD_JPY")
        .with_order_plan(plan, prepared_at)
        .submission_uncertain("timeout")
    )
    repository = _StateRepository(
        CheckpointLoadResult(
            CheckpointLoadStatus.LOADED,
            _checkpoint(
                persisted,
                mutation=(
                    PendingBrokerMutation(
                        "submit_order",
                        persisted.snapshot.name,
                        plan.broker_request.client_reference,
                        prepared_at=prepared_at,
                    ),
                ),
            ),
        )
    )
    broker = FakeBroker()
    broker.transactions = BrokerTransactionBatch(
        (
            BrokerTransaction(
                "202",
                "ORDER_FILL",
                order_id="external-order",
                trade_id="external-trade",
                pair="USD_JPY",
                units=100,
                price=150.01,
                occurred_at=datetime(2026, 1, 2, 10, 0, 1),
            ),
        ),
        "202",
    )
    broker.positions["external-trade"] = PositionSnapshot(
        "external",
        "USD_JPY",
        OrderState.FILLED,
        TradeState.OPEN,
        order_id="external-order",
        trade_id="external-trade",
        life=True,
        direction=1,
        target_price=150.01,
    )
    service = _service(repository, broker)

    result = service.restore_and_reconcile()

    assert result.state is PortfolioStartupState.QUARANTINED
    assert service.pending_mutations
    assert service.slots[0] is not None
    assert service.slots[0].snapshot.trade_id is None


@pytest.mark.contract
def test_startup_reconciliation_rejects_shape_match_without_transaction_time():
    plan = _plan("missing-time")
    prepared_at = datetime(2026, 1, 2, 10, 0, 0)
    persisted = (
        ManagedPosition.registered(plan.intent.name, "USD_JPY")
        .with_order_plan(plan, prepared_at)
        .submission_uncertain("timeout")
    )
    repository = _StateRepository(
        CheckpointLoadResult(
            CheckpointLoadStatus.LOADED,
            _checkpoint(
                persisted,
                mutation=(
                    PendingBrokerMutation(
                        "submit_order",
                        persisted.snapshot.name,
                        plan.broker_request.client_reference,
                        prepared_at=prepared_at,
                    ),
                ),
            ),
        )
    )
    broker = FakeBroker()
    broker.transactions = BrokerTransactionBatch(
        (
            BrokerTransaction(
                "203",
                "LIMIT_ORDER",
                order_id="shape-only-order",
                pair="USD_JPY",
                units=100,
                price=150.0,
            ),
        ),
        "203",
    )
    service = _service(repository, broker)

    result = service.restore_and_reconcile()

    assert result.state is PortfolioStartupState.RECONCILING
    assert service.transaction_cursor == "100"
    assert service.pending_mutations


@pytest.mark.contract
def test_startup_reconciliation_submits_prepared_order_once():
    plan = _plan("prepared-restart")
    persisted = ManagedPosition.registered(
        plan.intent.name,
        "USD_JPY",
    ).with_order_plan(plan, datetime(2026, 1, 2, 10, 0, 0))
    repository = _StateRepository(
        CheckpointLoadResult(
            CheckpointLoadStatus.LOADED,
            _checkpoint(persisted),
        )
    )
    broker = FakeBroker()
    service = _service(repository, broker)

    first = service.restore_and_reconcile()

    assert first.state is PortfolioStartupState.READY
    assert len(broker.requests) == 1
    assert service.slots[0] is not None
    assert service.slots[0].runtime.submission_phase is SubmissionPhase.PENDING
    assert service.pending_mutations == ()
    assert repository.saved[-1].pending_mutations == ()


@pytest.mark.contract
def test_startup_prepared_terminal_stops_remaining_submissions():
    first_plan = _plan("prepared-terminal", target=150.0)
    second_plan = _plan("prepared-blocked", target=150.2)
    first = ManagedPosition.registered(
        first_plan.intent.name,
        "USD_JPY",
    ).with_order_plan(first_plan, datetime(2026, 1, 2, 10, 0, 0))
    second = ManagedPosition.registered(
        second_plan.intent.name,
        "USD_JPY",
    ).with_order_plan(second_plan, datetime(2026, 1, 2, 10, 0, 0))
    checkpoint = replace(
        _checkpoint(first),
        slots=(first, second) + (None,) * 13,
    )
    repository = _StateRepository(
        CheckpointLoadResult(CheckpointLoadStatus.LOADED, checkpoint)
    )

    class _TerminalBroker(FakeBroker):
        def submit(self, request):
            self.requests.append(request)
            return OrderSubmissionResult.terminal(
                "entry closed existing trade",
                affected_trade_ids=("existing-trade",),
            )

    broker = _TerminalBroker()
    service = _service(repository, broker)

    result = service.restore_and_reconcile()

    assert result.state is PortfolioStartupState.QUARANTINED
    assert len(broker.requests) == 1


@pytest.mark.contract
def test_startup_prepared_unknown_remains_reconcilable_after_broker_delay():
    plan = _plan("prepared-delayed")
    persisted = ManagedPosition.registered(
        plan.intent.name,
        "USD_JPY",
    ).with_order_plan(plan, datetime(2026, 1, 2, 10, 0, 0))
    repository = _StateRepository(
        CheckpointLoadResult(
            CheckpointLoadStatus.LOADED,
            _checkpoint(persisted),
        )
    )

    class _DelayedBroker(FakeBroker):
        def submit(self, request):
            self.requests.append(request)
            self.transactions = BrokerTransactionBatch(
                (
                    BrokerTransaction(
                        "101",
                        "LIMIT_ORDER",
                        order_id="delayed-order",
                        client_reference=request.client_reference,
                        pair=request.instrument,
                        units=request.units,
                        price=request.price,
                        occurred_at=datetime(2026, 1, 2, 10, 0, 1),
                    ),
                ),
                "101",
            )
            self.orders["delayed-order"] = PositionSnapshot(
                plan.intent.name,
                request.instrument,
                OrderState.PENDING,
                TradeState.NONE,
                order_id="delayed-order",
                life=True,
                direction=1,
                target_price=request.price,
                units=abs(request.units),
            )
            return OrderSubmissionResult.unknown("timeout")

    broker = _DelayedBroker()
    service = _service(repository, broker)

    startup = service.restore_and_reconcile()

    assert startup.state is PortfolioStartupState.RECONCILING
    assert service.pending_mutations
    assert service.reconcile_pending_mutations() is True
    assert service.startup_state is PortfolioStartupState.READY
    assert service.pending_mutations == ()
    assert service.slots[0] is not None
    assert service.slots[0].snapshot.order_id == "delayed-order"


@pytest.mark.contract
@pytest.mark.parametrize(
    ("load_status", "state_writable"),
    [
        (CheckpointLoadStatus.LOADED_FROM_BACKUP, True),
        (CheckpointLoadStatus.LOADED, False),
    ],
)
def test_startup_reconciliation_never_submits_untrusted_prepared_checkpoint(
    load_status,
    state_writable,
):
    plan = _plan("untrusted-prepared")
    persisted = ManagedPosition.registered(
        plan.intent.name,
        "USD_JPY",
    ).with_order_plan(plan, datetime(2026, 1, 2, 10, 0, 0))
    repository = _StateRepository(
        CheckpointLoadResult(
            load_status,
            _checkpoint(persisted),
        )
    )
    broker = FakeBroker()
    service = _service(
        repository,
        broker,
        state_writable=state_writable,
    )

    result = service.restore_and_reconcile()

    assert result.state is PortfolioStartupState.QUARANTINED
    assert broker.requests == []


@pytest.mark.contract
def test_startup_reconciliation_does_not_submit_prepared_with_broker_orphan():
    plan = _plan("prepared-with-orphan")
    persisted = ManagedPosition.registered(
        plan.intent.name,
        "USD_JPY",
    ).with_order_plan(plan, datetime(2026, 1, 2, 10, 0, 0))
    repository = _StateRepository(
        CheckpointLoadResult(
            CheckpointLoadStatus.LOADED,
            _checkpoint(persisted),
        )
    )
    broker = FakeBroker()
    broker.orders["external-order"] = PositionSnapshot(
        "external",
        "USD_JPY",
        OrderState.PENDING,
        TradeState.NONE,
        order_id="external-order",
        life=True,
    )
    service = _service(repository, broker)

    result = service.restore_and_reconcile()

    assert result.state is PortfolioStartupState.QUARANTINED
    assert broker.requests == []


@pytest.mark.contract
@pytest.mark.parametrize(
    ("terminal_kind", "expected_phase"),
    [
        ("ORDER_CANCEL", SubmissionPhase.CANCELLED),
        ("LIMIT_ORDER_REJECT", SubmissionPhase.REJECTED),
    ],
)
def test_startup_reconciliation_resolves_uncertain_submit_terminal_transaction(
    terminal_kind,
    expected_phase,
):
    plan = _plan(f"uncertain-{terminal_kind.lower()}")
    persisted = (
        ManagedPosition.registered(plan.intent.name, "USD_JPY")
        .with_order_plan(plan, datetime(2026, 1, 2, 10, 0, 0))
        .submission_uncertain("timeout")
        .with_runtime(submission_phase=SubmissionPhase.SUBMITTING)
    )
    repository = _StateRepository(
        CheckpointLoadResult(
            CheckpointLoadStatus.LOADED,
            _checkpoint(
                persisted,
                mutation=(
                    PendingBrokerMutation(
                        "submit_order",
                        persisted.snapshot.name,
                        plan.broker_request.client_reference,
                    ),
                ),
            ),
        )
    )
    broker = FakeBroker()
    terminal = BrokerTransaction(
        "102",
        terminal_kind,
        order_id="101",
        client_reference=plan.broker_request.client_reference,
        pair="USD_JPY",
        units=100,
        price=150.0,
        reason="CLIENT_REQUEST" if terminal_kind == "ORDER_CANCEL" else "PRICE_INVALID",
    )
    transactions = (terminal,)
    if terminal_kind == "ORDER_CANCEL":
        transactions = (
            BrokerTransaction(
                "101",
                "LIMIT_ORDER",
                order_id="101",
                client_reference=plan.broker_request.client_reference,
                pair="USD_JPY",
                units=100,
                price=150.0,
            ),
            terminal,
        )
    broker.transactions = BrokerTransactionBatch(transactions, "102")
    service = _service(repository, broker)

    result = service.restore_and_reconcile()

    assert result.state is PortfolioStartupState.READY
    assert service.slots[0] is not None
    assert service.slots[0].snapshot.life is False
    assert service.slots[0].runtime.submission_phase is expected_phase
    assert service.pending_mutations == ()
    assert service.transaction_cursor == "102"


@pytest.mark.contract
def test_startup_reconciliation_promotes_normally_pending_order_filled_while_stopped():
    plan = _plan("filled-while-stopped")
    persisted = (
        ManagedPosition.registered(plan.intent.name, "USD_JPY")
        .with_order_plan(plan, datetime(2026, 1, 2, 10, 0, 0))
        .pending("order-1")
    )
    repository = _StateRepository(
        CheckpointLoadResult(
            CheckpointLoadStatus.LOADED,
            _checkpoint(persisted),
        )
    )
    broker = FakeBroker()
    broker.transactions = BrokerTransactionBatch(
        (
            BrokerTransaction(
                "101",
                "ORDER_FILL",
                order_id="order-1",
                trade_id="trade-1",
                pair="USD_JPY",
                units=100,
                price=150.01,
            ),
        ),
        "101",
    )
    broker.positions["trade-1"] = PositionSnapshot(
        plan.intent.name,
        "USD_JPY",
        OrderState.FILLED,
        TradeState.OPEN,
        order_id="order-1",
        trade_id="trade-1",
        life=True,
        direction=1,
        target_price=150.01,
        current_stop_loss=149.9,
    )
    service = _service(repository, broker)

    result = service.restore_and_reconcile()

    assert result.state is PortfolioStartupState.READY
    assert service.slots[0] is not None
    assert service.slots[0].snapshot.trade_id == "trade-1"
    assert service.slots[0].runtime.order_plan == plan


@pytest.mark.contract
def test_startup_reconciliation_applies_order_cancelled_while_stopped():
    plan = _plan("cancelled-while-stopped")
    persisted = (
        ManagedPosition.registered(plan.intent.name, "USD_JPY")
        .with_order_plan(plan, datetime(2026, 1, 2, 10, 0, 0))
        .pending("order-1")
    )
    repository = _StateRepository(
        CheckpointLoadResult(
            CheckpointLoadStatus.LOADED,
            _checkpoint(persisted),
        )
    )
    broker = FakeBroker()
    broker.orders["order-1"] = PositionSnapshot(
        plan.intent.name,
        "USD_JPY",
        OrderState.CANCELLED,
        TradeState.NONE,
        order_id="order-1",
        life=False,
    )
    service = _service(repository, broker)

    result = service.restore_and_reconcile()

    assert result.state is PortfolioStartupState.READY
    assert service.slots[0] is not None
    assert service.slots[0].snapshot.order_state is OrderState.CANCELLED
    assert service.slots[0].snapshot.life is False


@pytest.mark.contract
def test_startup_reconciliation_reports_trade_closed_while_stopped_once():
    plan = _plan("closed-while-stopped")
    persisted = (
        ManagedPosition.registered(plan.intent.name, "USD_JPY")
        .with_order_plan(plan, datetime(2026, 1, 2, 10, 0, 0))
        .pending("order-1")
        .filled("trade-1", datetime(2026, 1, 2, 10, 1, 0))
    )
    repository = _StateRepository(
        CheckpointLoadResult(
            CheckpointLoadStatus.LOADED,
            _checkpoint(persisted),
        )
    )
    broker = FakeBroker()
    broker.trades["trade-1"] = PositionSnapshot(
        plan.intent.name,
        "USD_JPY",
        OrderState.FILLED,
        TradeState.CLOSED,
        order_id="order-1",
        trade_id="trade-1",
        life=False,
        direction=1,
        target_price=150.0,
        units=100,
        realized_pl=25,
        average_close_price=150.02,
    )
    service = _service(repository, broker)

    result = service.restore_and_reconcile()
    second = service.restore_and_reconcile()

    assert result.state is PortfolioStartupState.READY
    assert second.state is PortfolioStartupState.READY
    assert service.slots[0] is not None
    assert service.slots[0].snapshot.trade_state is TradeState.CLOSED
    assert len(service.position_service.history.records) == 1
    assert service.position_service.history.records[0]["tradeID"] == "trade-1"


@pytest.mark.contract
def test_runtime_reconciliation_resolves_unknown_cancel_without_restart():
    plan = _plan("runtime-cancel")
    position = (
        ManagedPosition.registered(plan.intent.name, "USD_JPY")
        .with_order_plan(plan, datetime(2026, 1, 2, 10, 0, 0))
        .pending("order-1")
    )
    repository = _StateRepository(
        CheckpointLoadResult(CheckpointLoadStatus.MISSING)
    )
    broker = FakeBroker()
    broker.orders["order-1"] = PositionSnapshot(
        plan.intent.name,
        "USD_JPY",
        OrderState.CANCELLED,
        TradeState.NONE,
        order_id="order-1",
        life=False,
    )
    service = _service(repository, broker)
    service.startup_state = PortfolioStartupState.READY
    service.slots[0] = position
    service.transaction_cursor = "100"
    service.pending_mutations = (
        PendingBrokerMutation(
            "cancel_order",
            plan.intent.name,
            plan.broker_request.client_reference,
            "order-1",
            "timeout",
        ),
    )

    resolved = service.reconcile_pending_mutations()

    assert resolved is True
    assert service.pending_mutations == ()
    assert service.slots[0] is not None
    assert service.slots[0].snapshot.life is False


@pytest.mark.contract
def test_runtime_cancel_reconciliation_matches_slot_by_order_id_not_name():
    first_plan = _plan("same-name", target=150.0)
    second_plan = _plan("same-name", target=150.2)
    first = (
        ManagedPosition.registered("same-name", "USD_JPY")
        .with_order_plan(first_plan, datetime(2026, 1, 2, 10, 0, 0))
        .pending("order-1")
    )
    second = (
        ManagedPosition.registered("same-name", "USD_JPY")
        .with_order_plan(second_plan, datetime(2026, 1, 2, 10, 0, 0))
        .pending("order-2")
    )
    repository = _StateRepository(
        CheckpointLoadResult(CheckpointLoadStatus.MISSING)
    )
    broker = FakeBroker()
    broker.orders["order-2"] = PositionSnapshot(
        "same-name",
        "USD_JPY",
        OrderState.CANCELLED,
        TradeState.NONE,
        order_id="order-2",
        life=False,
    )
    service = _service(repository, broker)
    service.startup_state = PortfolioStartupState.READY
    service.slots[0] = first
    service.slots[1] = second
    service.transaction_cursor = "100"
    service.pending_mutations = (
        PendingBrokerMutation(
            "cancel_order",
            "same-name",
            second_plan.broker_request.client_reference,
            "order-2",
            "timeout",
        ),
    )

    assert service.reconcile_pending_mutations() is True

    assert service.slots[0] is not None
    assert service.slots[0].snapshot.order_state is OrderState.PENDING
    assert service.slots[1] is not None
    assert service.slots[1].snapshot.order_state is OrderState.CANCELLED


@pytest.mark.contract
def test_runtime_cancel_reconciliation_promotes_order_filled_during_cancel():
    plan = _plan("cancel-filled")
    position = (
        ManagedPosition.registered(plan.intent.name, "USD_JPY")
        .with_order_plan(plan, datetime(2026, 1, 2, 10, 0, 0))
        .pending("order-1")
    )
    repository = _StateRepository(
        CheckpointLoadResult(CheckpointLoadStatus.MISSING)
    )
    broker = FakeBroker()
    broker.transactions = BrokerTransactionBatch(
        (
            BrokerTransaction(
                "101",
                "ORDER_FILL",
                order_id="order-1",
                trade_id="trade-1",
                pair="USD_JPY",
                units=100,
                price=150.01,
            ),
        ),
        "101",
    )
    broker.orders["order-1"] = PositionSnapshot(
        plan.intent.name,
        "USD_JPY",
        OrderState.FILLED,
        TradeState.OPEN,
        order_id="order-1",
        trade_id="trade-1",
        life=True,
    )
    broker.positions["trade-1"] = PositionSnapshot(
        plan.intent.name,
        "USD_JPY",
        OrderState.FILLED,
        TradeState.OPEN,
        order_id="order-1",
        trade_id="trade-1",
        life=True,
        direction=1,
        target_price=150.01,
    )
    service = _service(repository, broker)
    service.startup_state = PortfolioStartupState.RECONCILING
    service.slots[0] = position
    service.transaction_cursor = "100"
    service.pending_mutations = (
        PendingBrokerMutation(
            "cancel_order",
            plan.intent.name,
            plan.broker_request.client_reference,
            "order-1",
            "timeout",
        ),
    )

    assert service.reconcile_pending_mutations() is True

    assert service.startup_state is PortfolioStartupState.READY
    assert service.slots[0] is not None
    assert service.slots[0].snapshot.trade_id == "trade-1"
    assert service.slots[0].snapshot.trade_state is TradeState.OPEN


@pytest.mark.contract
def test_runtime_reconciliation_applies_other_slot_fill_before_cursor_advance():
    filled_plan = _plan("filled-other-slot", target=150.0)
    cancelled_plan = _plan("cancelled-slot", target=150.2)
    filled_position = (
        ManagedPosition.registered(filled_plan.intent.name, "USD_JPY")
        .with_order_plan(filled_plan, datetime(2026, 1, 2, 10, 0, 0))
        .pending("order-fill")
    )
    cancelled_position = (
        ManagedPosition.registered(cancelled_plan.intent.name, "USD_JPY")
        .with_order_plan(cancelled_plan, datetime(2026, 1, 2, 10, 0, 0))
        .pending("order-cancel")
    )
    repository = _StateRepository(
        CheckpointLoadResult(CheckpointLoadStatus.MISSING)
    )
    broker = FakeBroker()
    broker.transactions = BrokerTransactionBatch(
        (
            BrokerTransaction(
                "101",
                "ORDER_FILL",
                order_id="order-fill",
                trade_id="trade-fill",
                pair="USD_JPY",
                units=100,
                price=150.01,
            ),
        ),
        "102",
    )
    broker.positions["trade-fill"] = PositionSnapshot(
        filled_plan.intent.name,
        "USD_JPY",
        OrderState.FILLED,
        TradeState.OPEN,
        order_id="order-fill",
        trade_id="trade-fill",
        life=True,
        direction=1,
        target_price=150.01,
    )
    broker.orders["order-cancel"] = PositionSnapshot(
        cancelled_plan.intent.name,
        "USD_JPY",
        OrderState.CANCELLED,
        TradeState.NONE,
        order_id="order-cancel",
        life=False,
    )
    service = _service(repository, broker)
    service.startup_state = PortfolioStartupState.RECONCILING
    service.slots[0] = filled_position
    service.slots[1] = cancelled_position
    service.transaction_cursor = "100"
    service.pending_mutations = (
        PendingBrokerMutation(
            "cancel_order",
            cancelled_plan.intent.name,
            cancelled_plan.broker_request.client_reference,
            "order-cancel",
            "timeout",
        ),
    )

    assert service.reconcile_pending_mutations() is True

    assert service.transaction_cursor == "102"
    assert service.slots[0] is not None
    assert service.slots[0].snapshot.trade_id == "trade-fill"
    assert service.slots[1] is not None
    assert service.slots[1].snapshot.order_state is OrderState.CANCELLED


@pytest.mark.contract
def test_runtime_reconciliation_keeps_unknown_cancel_when_order_is_unobservable():
    plan = _plan("cancel-unobservable")
    position = (
        ManagedPosition.registered(plan.intent.name, "USD_JPY")
        .with_order_plan(plan, datetime(2026, 1, 2, 10, 0, 0))
        .pending("order-1")
    )
    repository = _StateRepository(
        CheckpointLoadResult(CheckpointLoadStatus.MISSING)
    )
    broker = FakeBroker()
    service = _service(repository, broker)
    service.startup_state = PortfolioStartupState.READY
    service.slots[0] = position
    service.transaction_cursor = "100"
    service.pending_mutations = (
        PendingBrokerMutation(
            "cancel_order",
            plan.intent.name,
            plan.broker_request.client_reference,
            "order-1",
            "timeout",
        ),
    )

    assert service.reconcile_pending_mutations() is False

    assert service.pending_mutations
    assert service.slots[0] is not None
    assert service.slots[0].snapshot.life is True


@pytest.mark.contract
def test_startup_keeps_unobservable_cancel_available_for_reconciliation():
    plan = _plan("startup-cancel-unobservable")
    position = (
        ManagedPosition.registered(plan.intent.name, "USD_JPY")
        .with_order_plan(plan, datetime(2026, 1, 2, 10, 0, 0))
        .pending("order-1")
    )
    repository = _StateRepository(
        CheckpointLoadResult(
            CheckpointLoadStatus.LOADED,
            _checkpoint(
                position,
                mutation=(
                    PendingBrokerMutation(
                        "cancel_order",
                        plan.intent.name,
                        plan.broker_request.client_reference,
                        "order-1",
                        "timeout",
                    ),
                ),
            ),
        )
    )
    broker = FakeBroker()
    service = _service(repository, broker)

    result = service.restore_and_reconcile()

    assert result.state is PortfolioStartupState.RECONCILING
    assert service.pending_mutations
    assert service.slots[0] is not None
    assert service.slots[0].snapshot.life is True
    registration = service.register_plans([_plan("blocked")], submit=True)
    assert registration.rejected == (("blocked", "broker_reconciliation"),)


@pytest.mark.contract
def test_startup_cancel_unknown_resolves_by_broker_reference_without_local_slot():
    repository = _StateRepository(
        CheckpointLoadResult(CheckpointLoadStatus.MISSING)
    )

    class _UnknownCancelBroker(FakeBroker):
        def cancel_order(self, order_id):
            snapshot = self.orders[order_id]
            self.orders[order_id] = PositionSnapshot(
                **{
                    **snapshot.__dict__,
                    "order_state": OrderState.CANCELLED,
                    "life": False,
                }
            )
            return ExecutionResult(
                False,
                message="timeout",
                state=MutationState.UNKNOWN,
            )

    broker = _UnknownCancelBroker()
    broker.orders["startup-order"] = PositionSnapshot(
        "ogami-oanda",
        "USD_JPY",
        OrderState.PENDING,
        TradeState.NONE,
        order_id="startup-order",
        life=True,
    )
    service = _service(repository, broker)
    service.startup_state = PortfolioStartupState.READY

    assert service.cancel_pending_on_start(True) == ()
    assert service.pending_mutations
    assert service.reconcile_pending_mutations() is True
    assert service.pending_mutations == ()


@pytest.mark.contract
def test_runtime_reconciliation_keeps_cursor_when_submit_is_unresolved():
    plan = _plan("cursor-replay")
    position = (
        ManagedPosition.registered(plan.intent.name, "USD_JPY")
        .with_order_plan(plan, datetime(2026, 1, 2, 10, 0, 0))
        .submission_uncertain("timeout")
    )
    repository = _StateRepository(
        CheckpointLoadResult(CheckpointLoadStatus.MISSING)
    )
    broker = FakeBroker()
    broker.transactions = BrokerTransactionBatch(
        (
            BrokerTransaction(
                "101",
                "LIMIT_ORDER",
                order_id="order-1",
                client_reference=plan.broker_request.client_reference,
                pair="USD_JPY",
                units=100,
                price=150.0,
                occurred_at=datetime(2026, 1, 2, 10, 0, 1),
            ),
        ),
        "101",
    )
    service = _service(repository, broker)
    service.startup_state = PortfolioStartupState.READY
    service.slots[0] = position
    service.transaction_cursor = "100"
    service.pending_mutations = (
        PendingBrokerMutation(
            "submit_order",
            plan.intent.name,
            plan.broker_request.client_reference,
            prepared_at=datetime(2026, 1, 2, 10, 0, 0),
        ),
    )

    assert service.reconcile_pending_mutations() is False

    assert service.transaction_cursor == "100"
    assert service.pending_mutations
    assert repository.saved[-1].transaction_cursor == "100"


@pytest.mark.contract
def test_unknown_close_reconciliation_reports_trade_once():
    plan = _plan("runtime-close")
    position = (
        ManagedPosition.registered(plan.intent.name, "USD_JPY")
        .with_order_plan(plan, datetime(2026, 1, 2, 10, 0, 0))
        .pending("order-1")
        .filled("trade-1", datetime(2026, 1, 2, 10, 1, 0))
    )
    repository = _StateRepository(
        CheckpointLoadResult(CheckpointLoadStatus.MISSING)
    )
    broker = FakeBroker()
    broker.trades["trade-1"] = PositionSnapshot(
        plan.intent.name,
        "USD_JPY",
        OrderState.FILLED,
        TradeState.CLOSED,
        order_id="order-1",
        trade_id="trade-1",
        life=False,
        direction=1,
        target_price=150.0,
        units=100,
        realized_pl=10,
        average_close_price=150.01,
    )
    service = _service(repository, broker)
    service.startup_state = PortfolioStartupState.READY
    service.slots[0] = position
    service.transaction_cursor = "100"
    service.pending_mutations = (
        PendingBrokerMutation(
            "close_trade",
            plan.intent.name,
            plan.broker_request.client_reference,
            "trade-1",
            "timeout",
        ),
    )

    assert service.reconcile_pending_mutations() is True
    assert service.reconcile_pending_mutations() is True

    history = service.position_service.history
    assert len(history.records) == 1
    assert history.records[0]["tradeID"] == "trade-1"
    assert service.position_service.closure_reporting.analytics.total_yen == 10


@pytest.mark.contract
@pytest.mark.parametrize("action", ["cancel_order", "close_trade", "amend_stop_loss"])
def test_startup_reconciliation_resolves_uncertain_non_submit_mutations(action):
    plan = _plan(f"uncertain-{action}")
    if action == "cancel_order":
        persisted = (
            ManagedPosition.registered(plan.intent.name, "USD_JPY")
            .with_order_plan(plan, datetime(2026, 1, 2, 10, 0, 0))
            .pending("order-1")
        )
        broker_reference = "order-1"
    else:
        persisted = (
            ManagedPosition.registered(plan.intent.name, "USD_JPY")
            .with_order_plan(plan, datetime(2026, 1, 2, 10, 0, 0))
            .pending("order-1")
            .filled("trade-1", datetime(2026, 1, 2, 10, 1, 0))
            .with_runtime(current_stop_loss=149.9)
        )
        broker_reference = "trade-1"
    mutation = PendingBrokerMutation(
        action,
        persisted.snapshot.name,
        plan.broker_request.client_reference,
        broker_reference,
        "recovery",
        150.01 if action == "amend_stop_loss" else None,
    )
    repository = _StateRepository(
        CheckpointLoadResult(
            CheckpointLoadStatus.LOADED,
            _checkpoint(persisted, mutation=(mutation,)),
        )
    )
    broker = FakeBroker()
    if action == "cancel_order":
        broker.orders["order-1"] = PositionSnapshot(
            persisted.snapshot.name,
            "USD_JPY",
            OrderState.CANCELLED,
            TradeState.NONE,
            order_id="order-1",
            life=False,
        )
    elif action == "close_trade":
        broker.trades["trade-1"] = PositionSnapshot(
            persisted.snapshot.name,
            "USD_JPY",
            OrderState.FILLED,
            TradeState.CLOSED,
            order_id="order-1",
            trade_id="trade-1",
            life=False,
            direction=1,
            target_price=150.0,
            realized_pl=10,
            average_close_price=150.01,
        )
    elif action == "amend_stop_loss":
        broker.positions["trade-1"] = PositionSnapshot(
            persisted.snapshot.name,
            "USD_JPY",
            OrderState.FILLED,
            TradeState.OPEN,
            order_id="order-1",
            trade_id="trade-1",
            life=True,
            direction=1,
            target_price=150.0,
            current_stop_loss=150.01,
        )
    service = _service(repository, broker)

    result = service.restore_and_reconcile()

    assert result.state is PortfolioStartupState.READY
    assert service.pending_mutations == ()
    assert service.slots[0] is not None
    if action == "cancel_order":
        assert service.slots[0].snapshot.life is False
    elif action == "close_trade":
        assert service.slots[0].snapshot.trade_state is TradeState.CLOSED
    else:
        assert service.slots[0].runtime.current_stop_loss == 150.01


@pytest.mark.contract
@pytest.mark.parametrize(
    "load_status",
    [CheckpointLoadStatus.MISSING, CheckpointLoadStatus.QUARANTINED],
)
def test_startup_reconciliation_quarantines_unmanaged_broker_positions(load_status):
    repository = _StateRepository(CheckpointLoadResult(load_status))
    broker = FakeBroker()
    broker.positions["external"] = PositionSnapshot(
        "external",
        "USD_JPY",
        OrderState.FILLED,
        TradeState.OPEN,
        trade_id="external",
        life=True,
        direction=1,
        target_price=150.0,
    )
    service = _service(repository, broker)

    result = service.restore_and_reconcile()
    registration = service.register_plans([_plan("blocked")], submit=True)

    assert result.state is PortfolioStartupState.QUARANTINED
    assert registration.rejected == (("blocked", "portfolio_quarantined"),)
    assert broker.requests == []


@pytest.mark.contract
def test_startup_reconciliation_allows_clean_first_start():
    repository = _StateRepository(
        CheckpointLoadResult(CheckpointLoadStatus.MISSING)
    )
    broker = FakeBroker()
    service = _service(repository, broker)

    result = service.restore_and_reconcile()

    assert result.state is PortfolioStartupState.READY
    assert result.restored == ()
    assert repository.saved


@pytest.mark.contract
def test_register_plans_auto_reconciles_before_first_broker_mutation():
    repository = _StateRepository(
        CheckpointLoadResult(CheckpointLoadStatus.MISSING)
    )
    broker = FakeBroker()
    service = _service(repository, broker)

    registration = service.register_plans([_plan("auto-start")], submit=True)

    assert registration.accepted == ("auto-start",)
    assert service.startup_state is PortfolioStartupState.READY
    assert len(broker.requests) == 1
    assert repository.saved


@pytest.mark.contract
def test_register_plans_auto_quarantines_unmanaged_broker_state():
    repository = _StateRepository(
        CheckpointLoadResult(CheckpointLoadStatus.MISSING)
    )
    broker = FakeBroker()
    broker.positions["external"] = PositionSnapshot(
        "external",
        "USD_JPY",
        OrderState.FILLED,
        TradeState.OPEN,
        trade_id="external",
        life=True,
        direction=1,
        target_price=150.0,
    )
    service = _service(repository, broker)

    registration = service.register_plans([_plan("blocked")], submit=True)

    assert registration.rejected == (("blocked", "portfolio_quarantined"),)
    assert service.startup_state is PortfolioStartupState.QUARANTINED
    assert broker.requests == []


@pytest.mark.contract
def test_startup_reconciliation_preserves_terminal_effect_quarantine():
    plan = _plan("terminal-restart")
    terminal = (
        ManagedPosition.registered("terminal-restart", "USD_JPY")
        .with_order_plan(plan, datetime(2026, 1, 2, 10, 0, 0))
        .rejected("entry reduced existing trade")
        .with_runtime(submission_phase=SubmissionPhase.TERMINAL)
    )
    repository = _StateRepository(
        CheckpointLoadResult(
            CheckpointLoadStatus.LOADED,
            _checkpoint(terminal),
        )
    )
    broker = FakeBroker()
    service = _service(repository, broker)

    startup = service.restore_and_reconcile()
    registration = service.register_plans([_plan("blocked")], submit=True)

    assert startup.state is PortfolioStartupState.QUARANTINED
    assert startup.reason == "terminal_broker_effect"
    assert registration.rejected == (("blocked", "portfolio_quarantined"),)
    assert broker.requests == []


@pytest.mark.contract
def test_csv_history_newer_than_checkpoint_remains_reporting_source_of_truth():
    inactive = ManagedPosition.registered("history-newer", "USD_JPY")
    checkpoint = _checkpoint(inactive)
    repository = _StateRepository(
        CheckpointLoadResult(CheckpointLoadStatus.LOADED, checkpoint)
    )
    broker = FakeBroker()
    history = InMemoryTradeHistoryRepository()
    history.append(
        {
            "name": "newer-close",
            "name_only": "newer-",
            "pair": "USD_JPY",
            "res": "75",
            "pl_per_units": "7.5",
            "tradeID": "trade-newer",
            "lc_change": "",
        }
    )
    clock = FixedClock(datetime(2026, 1, 2, 10, 5, 0))
    position_service = PositionService(
        broker,
        broker,
        FakeNotifier(),
        history,
        clock,
    )
    service = PositionPortfolioService(
        "USD_JPY",
        position_service,
        broker,
        broker,
        state_repository=repository,
        account_hash=account_identity_hash("id"),
    )

    result = service.restore_and_reconcile()

    assert result.state is PortfolioStartupState.READY
    analytics = service.position_service.closure_reporting.analytics
    assert analytics.total_yen == 75
    assert analytics.before_latest_name == "newer-close"
    assert "trade_closed:trade-newer" in (
        service.position_service.closure_reporting._reported_event_ids
    )
