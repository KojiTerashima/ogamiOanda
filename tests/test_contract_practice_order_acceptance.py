from __future__ import annotations

import pytest
from datetime import datetime, timezone

from ogami_oanda.application.ports.broker import (
    ExecutionResult,
    MutationState,
    OrderSubmissionResult,
)
from ogami_oanda.application.ports.market_data import MarketQuote
from ogami_oanda.application.services.practice_order_acceptance_service import (
    PracticeAcceptanceError,
    PracticeOrderAcceptanceService,
)
from ogami_oanda.domain.orders.models import OrderContext, OrderIntent
from ogami_oanda.domain.orders.models import Direction
from ogami_oanda.domain.orders.models import OrderType
from ogami_oanda.domain.positions.models import (
    OrderState,
    PositionSnapshot,
    TradeState,
)
from tests.fakes import FakeBroker, FakeMarketData


class _AcceptanceBroker(FakeBroker):
    def __init__(self, *, fail_on_submit_number=None, fail_cleanup=False):
        super().__init__()
        self.fail_on_submit_number = fail_on_submit_number
        self.fail_cleanup = fail_cleanup
        self.submission_count = 0

    def submit(self, request):
        self.requests.append(request)
        self.submission_count += 1
        if self.submission_count == self.fail_on_submit_number:
            raise RuntimeError("simulated workflow failure")
        if request.order_type is OrderType.MARKET:
            trade_id = f"trade-{self.submission_count}"
            order_id = f"order-{self.submission_count}"
            self.positions[trade_id] = PositionSnapshot(
                request.client_reference,
                request.instrument,
                OrderState.FILLED,
                TradeState.OPEN,
                order_id=order_id,
                trade_id=trade_id,
                life=True,
                direction=1 if request.units > 0 else -1,
                target_price=request.price,
                units=abs(request.units),
                current_stop_loss=request.stop_loss_price,
                client_reference=request.client_reference,
            )
            return OrderSubmissionResult.filled(
                order_id=order_id,
                trade_id=trade_id,
                fill_price=request.price,
            )
        order_id = f"order-{self.submission_count}"
        self.orders[order_id] = PositionSnapshot(
            request.client_reference,
            request.instrument,
            OrderState.PENDING,
            TradeState.NONE,
            order_id=order_id,
            life=True,
            direction=1 if request.units > 0 else -1,
            target_price=request.price,
            units=abs(request.units),
            client_reference=request.client_reference,
        )
        return OrderSubmissionResult.pending(order_id)

    def cancel_order(self, order_id):
        self.commands.append(("cancel_order", (order_id,)))
        if self.fail_cleanup:
            return ExecutionResult(False, message="cleanup rejected")
        snapshot = self.orders[order_id]
        self.orders[order_id] = PositionSnapshot(
            **{
                **snapshot.__dict__,
                "order_state": OrderState.CANCELLED,
                "life": False,
            }
        )
        return ExecutionResult(True, order_id)

    def close_trade(self, trade_id, units=None):
        self.commands.append(("close_trade", (trade_id, units)))
        if self.fail_cleanup:
            return ExecutionResult(False, message="cleanup rejected")
        snapshot = self.positions[trade_id]
        self.positions[trade_id] = PositionSnapshot(
            **{
                **snapshot.__dict__,
                "trade_state": TradeState.CLOSED,
                "life": False,
                "realized_pl": -0.01,
                "average_close_price": snapshot.target_price,
            }
        )
        return ExecutionResult(True, trade_id)

    def pending_orders(self):
        return [snapshot for snapshot in self.orders.values() if snapshot.life]

    def open_positions(self):
        return [snapshot for snapshot in self.positions.values() if snapshot.life]


def _market():
    prices = {"USD_JPY": 150.0, "EUR_USD": 1.1, "AUD_USD": 0.65}

    class _Market(FakeMarketData):
        def current_quote(self, pair):
            mid = self.prices[pair]
            spread = 0.01 if pair == "USD_JPY" else 0.0001
            return MarketQuote(
                pair,
                mid - spread / 2,
                mid + spread / 2,
                mid,
                True,
            )

    return _Market({}, prices)


@pytest.mark.contract
def test_practice_acceptance_runs_three_pair_order_matrix_and_cleans_up():
    broker = _AcceptanceBroker()
    service = PracticeOrderAcceptanceService(_market(), broker, broker)

    report = service.run(("USD_JPY", "EUR_USD", "AUD_USD"))

    assert report.success is True
    assert len(report.operations) == 9
    assert {
        (operation.pair, operation.order_type)
        for operation in report.operations
    } == {
        (pair, order_type)
        for pair in ("USD_JPY", "EUR_USD", "AUD_USD")
        for order_type in (OrderType.LIMIT, OrderType.STOP, OrderType.MARKET)
    }
    assert all(operation.cleaned_up for operation in report.operations)
    assert broker.pending_orders() == []
    assert broker.open_positions() == []
    assert [request.units for request in broker.requests] == [1] * 9


@pytest.mark.contract
def test_practice_acceptance_uses_unique_references_for_each_run():
    broker = _AcceptanceBroker()
    run_ids = iter(("run-a", "run-b"))
    service = PracticeOrderAcceptanceService(
        _market(),
        broker,
        broker,
        run_id_factory=run_ids.__next__,
    )

    service.run(("USD_JPY",))
    first_references = {
        request.client_reference for request in broker.requests
    }
    service.run(("USD_JPY",))
    second_references = {
        request.client_reference for request in broker.requests[3:]
    }

    assert first_references.isdisjoint(second_references)


@pytest.mark.contract
def test_practice_acceptance_aborts_when_account_is_not_clean():
    broker = _AcceptanceBroker()
    broker.orders["existing"] = PositionSnapshot(
        "existing",
        "USD_JPY",
        OrderState.PENDING,
        TradeState.NONE,
        order_id="existing",
        life=True,
    )
    service = PracticeOrderAcceptanceService(_market(), broker, broker)

    with pytest.raises(PracticeAcceptanceError, match="existing pending or open"):
        service.run(("USD_JPY",))

    assert broker.requests == []


@pytest.mark.contract
def test_practice_acceptance_cleans_created_resources_after_mid_workflow_failure():
    broker = _AcceptanceBroker(fail_on_submit_number=2)
    service = PracticeOrderAcceptanceService(_market(), broker, broker)

    with pytest.raises(
        PracticeAcceptanceError,
        match="simulated workflow failure",
    ) as error_info:
        service.run(("USD_JPY",))

    assert broker.pending_orders() == []
    assert broker.open_positions() == []
    assert len(error_info.value.operations) == 2
    assert error_info.value.operations[0].order_id == "order-1"
    assert error_info.value.operations[1].order_type is OrderType.STOP


@pytest.mark.contract
def test_practice_acceptance_recovers_resource_created_before_submit_exception():
    class _CreateThenRaiseBroker(_AcceptanceBroker):
        def submit(self, request):
            self.requests.append(request)
            self.orders["created-before-error"] = PositionSnapshot(
                "ogami-oanda",
                request.instrument,
                OrderState.PENDING,
                TradeState.NONE,
                order_id="created-before-error",
                life=True,
                direction=1,
                target_price=request.price,
                units=abs(request.units),
                client_reference=request.client_reference,
            )
            raise RuntimeError("mapper failed after broker creation")

    broker = _CreateThenRaiseBroker()
    service = PracticeOrderAcceptanceService(_market(), broker, broker)

    with pytest.raises(
        PracticeAcceptanceError,
        match="mapper failed",
    ) as error_info:
        service.run(("USD_JPY",))

    assert broker.pending_orders() == []
    assert ("cancel_order", ("created-before-error",)) in broker.commands
    assert error_info.value.operations[0].order_id == "created-before-error"
    assert error_info.value.operations[0].cleaned_up is True


@pytest.mark.contract
def test_practice_acceptance_cleans_residual_order_after_unknown_submit():
    class _UnknownSubmitBroker(_AcceptanceBroker):
        def submit(self, request):
            self.requests.append(request)
            order_id = "unknown-order"
            self.orders[order_id] = PositionSnapshot(
                order_id,
                request.instrument,
                OrderState.PENDING,
                TradeState.NONE,
                order_id=order_id,
                life=True,
                direction=1,
                target_price=request.price,
                units=abs(request.units),
                client_reference=request.client_reference,
            )
            return OrderSubmissionResult.unknown("timeout")

    broker = _UnknownSubmitBroker()
    service = PracticeOrderAcceptanceService(_market(), broker, broker)

    with pytest.raises(PracticeAcceptanceError, match="was not pending"):
        service.run(("USD_JPY",))

    assert broker.pending_orders() == []
    assert broker.open_positions() == []
    assert ("cancel_order", ("unknown-order",)) in broker.commands


@pytest.mark.contract
def test_practice_acceptance_polls_for_delayed_unknown_submit_resource():
    class _DelayedUnknownSubmitBroker(_AcceptanceBroker):
        def __init__(self):
            super().__init__()
            self.pending_checks = 0

        def submit(self, request):
            self.requests.append(request)
            self.orders["delayed-order"] = PositionSnapshot(
                "ogami-oanda",
                request.instrument,
                OrderState.PENDING,
                TradeState.NONE,
                order_id="delayed-order",
                life=True,
                direction=1,
                target_price=request.price,
                units=abs(request.units),
                client_reference=request.client_reference,
            )
            return OrderSubmissionResult.unknown("timeout")

        def pending_orders(self):
            self.pending_checks += 1
            if self.pending_checks == 2:
                return []
            return super().pending_orders()

    broker = _DelayedUnknownSubmitBroker()
    sleeps = []
    service = PracticeOrderAcceptanceService(
        _market(),
        broker,
        broker,
        poll_attempts=2,
        poll_interval_seconds=0.25,
        sleeper=sleeps.append,
    )

    with pytest.raises(PracticeAcceptanceError, match="was not pending"):
        service.run(("USD_JPY",))

    assert ("cancel_order", ("delayed-order",)) in broker.commands
    assert sleeps == [0.25]


@pytest.mark.contract
def test_practice_acceptance_does_not_clean_unrelated_order_after_unknown_submit():
    class _ConcurrentSubmitBroker(_AcceptanceBroker):
        def submit(self, request):
            self.requests.append(request)
            self.orders["owned-order"] = PositionSnapshot(
                "owned-order",
                request.instrument,
                OrderState.PENDING,
                TradeState.NONE,
                order_id="owned-order",
                life=True,
                direction=1,
                target_price=request.price,
                units=abs(request.units),
                client_reference=request.client_reference,
            )
            self.orders["unrelated-order"] = PositionSnapshot(
                "unrelated-order",
                "EUR_USD",
                OrderState.PENDING,
                TradeState.NONE,
                order_id="unrelated-order",
                life=True,
                direction=-1,
                target_price=1.2,
                units=2,
            )
            return OrderSubmissionResult.unknown("timeout")

    broker = _ConcurrentSubmitBroker()
    service = PracticeOrderAcceptanceService(_market(), broker, broker)

    with pytest.raises(PracticeAcceptanceError, match="cleanup could not be confirmed"):
        service.run(("USD_JPY",))

    assert ("cancel_order", ("owned-order",)) in broker.commands
    assert ("cancel_order", ("unrelated-order",)) not in broker.commands
    assert {snapshot.order_id for snapshot in broker.pending_orders()} == {
        "unrelated-order"
    }


@pytest.mark.contract
def test_practice_acceptance_does_not_clean_ambiguous_unknown_submit_matches():
    class _AmbiguousSubmitBroker(_AcceptanceBroker):
        def submit(self, request):
            self.requests.append(request)
            for order_id in ("ambiguous-a", "ambiguous-b"):
                self.orders[order_id] = PositionSnapshot(
                    order_id,
                    request.instrument,
                    OrderState.PENDING,
                    TradeState.NONE,
                    order_id=order_id,
                    life=True,
                    direction=1,
                    target_price=request.price,
                    units=abs(request.units),
                )
            return OrderSubmissionResult.unknown("timeout")

    broker = _AmbiguousSubmitBroker()
    service = PracticeOrderAcceptanceService(_market(), broker, broker)

    with pytest.raises(PracticeAcceptanceError, match="cleanup could not be confirmed"):
        service.run(("USD_JPY",))

    assert broker.commands == []
    assert {snapshot.order_id for snapshot in broker.pending_orders()} == {
        "ambiguous-a",
        "ambiguous-b",
    }


@pytest.mark.contract
def test_practice_acceptance_does_not_claim_unique_shape_without_reference():
    class _ExternalSubmitBroker(_AcceptanceBroker):
        def submit(self, request):
            self.requests.append(request)
            self.orders["external-order"] = PositionSnapshot(
                "external-order",
                request.instrument,
                OrderState.PENDING,
                TradeState.NONE,
                order_id="external-order",
                life=True,
                direction=1,
                target_price=request.price,
                units=abs(request.units),
            )
            return OrderSubmissionResult.unknown("timeout")

    broker = _ExternalSubmitBroker()
    service = PracticeOrderAcceptanceService(_market(), broker, broker)

    with pytest.raises(PracticeAcceptanceError, match="cleanup could not be confirmed"):
        service.run(("USD_JPY",))

    assert broker.commands == []
    assert {snapshot.order_id for snapshot in broker.pending_orders()} == {
        "external-order"
    }


@pytest.mark.contract
@pytest.mark.parametrize("action", ["cancel", "close"])
def test_practice_acceptance_never_retries_unknown_cleanup_mutation(action):
    class _UnknownCleanupBroker(_AcceptanceBroker):
        def cancel_order(self, order_id):
            self.commands.append(("cancel_order", (order_id,)))
            return ExecutionResult(
                False,
                message="timeout",
                state=MutationState.UNKNOWN,
            )

        def close_trade(self, trade_id, units=None):
            self.commands.append(("close_trade", (trade_id, units)))
            return ExecutionResult(
                False,
                message="timeout",
                state=MutationState.UNKNOWN,
            )

        def submit(self, request):
            if action == "cancel":
                return super().submit(request)
            self.requests.append(request)
            trade_id = "unknown-close-trade"
            self.positions[trade_id] = PositionSnapshot(
                request.client_reference,
                request.instrument,
                OrderState.FILLED,
                TradeState.OPEN,
                trade_id=trade_id,
                life=True,
                direction=1,
                target_price=request.price,
                units=abs(request.units),
            )
            return OrderSubmissionResult.filled(
                order_id="market-order",
                trade_id=trade_id,
                fill_price=request.price,
            )

    broker = _UnknownCleanupBroker()
    service = PracticeOrderAcceptanceService(
        _market(),
        broker,
        broker,
        poll_attempts=1,
    )

    with pytest.raises(PracticeAcceptanceError, match="cleanup"):
        service.run(("USD_JPY",))

    command = "cancel_order" if action == "cancel" else "close_trade"
    assert sum(item[0] == command for item in broker.commands) == 1


@pytest.mark.contract
def test_practice_acceptance_closes_pending_order_that_fills_during_cancel():
    class _FillDuringCancelBroker(_AcceptanceBroker):
        def cancel_order(self, order_id):
            self.commands.append(("cancel_order", (order_id,)))
            snapshot = self.orders[order_id]
            trade_id = "trade-from-pending"
            self.orders[order_id] = PositionSnapshot(
                **{
                    **snapshot.__dict__,
                    "order_state": OrderState.FILLED,
                    "trade_state": TradeState.OPEN,
                    "trade_id": trade_id,
                    "life": True,
                }
            )
            self.positions[trade_id] = self.orders[order_id]
            return ExecutionResult(False, message="ORDER_ALREADY_FILLED")

        def pending_orders(self):
            return [
                snapshot
                for snapshot in self.orders.values()
                if snapshot.order_state is OrderState.PENDING
            ]

    broker = _FillDuringCancelBroker()
    service = PracticeOrderAcceptanceService(_market(), broker, broker)

    with pytest.raises(PracticeAcceptanceError, match="workflow stopped"):
        service.run(("USD_JPY",))

    assert broker.pending_orders() == []
    assert broker.open_positions() == []
    assert ("close_trade", ("trade-from-pending", None)) in broker.commands


@pytest.mark.contract
def test_practice_acceptance_finds_fill_when_order_trade_link_is_delayed():
    class _DelayedFillLinkBroker(_AcceptanceBroker):
        def cancel_order(self, order_id):
            self.commands.append(("cancel_order", (order_id,)))
            order = self.orders[order_id]
            self.orders[order_id] = PositionSnapshot(
                **{
                    **order.__dict__,
                    "order_state": OrderState.FILLED,
                    "life": False,
                }
            )
            self.positions["delayed-fill-trade"] = PositionSnapshot(
                "ogami-oanda",
                order.pair,
                OrderState.FILLED,
                TradeState.OPEN,
                trade_id="delayed-fill-trade",
                life=True,
                direction=order.direction,
                target_price=order.target_price,
                units=order.units,
                client_reference=order.client_reference,
            )
            return ExecutionResult(False, message="ORDER_ALREADY_FILLED")

        def pending_orders(self):
            return [
                snapshot
                for snapshot in self.orders.values()
                if snapshot.order_state is OrderState.PENDING
            ]

    broker = _DelayedFillLinkBroker()
    service = PracticeOrderAcceptanceService(_market(), broker, broker)

    with pytest.raises(PracticeAcceptanceError, match="cleanup failed"):
        service.run(("USD_JPY",))

    assert broker.pending_orders() == []
    assert broker.open_positions() == []
    assert ("close_trade", ("delayed-fill-trade", None)) in broker.commands


@pytest.mark.contract
def test_practice_acceptance_preserves_operations_when_final_query_fails():
    class _FinalQueryFailureBroker(_AcceptanceBroker):
        def __init__(self):
            super().__init__()
            self.pending_queries = 0

        def pending_orders(self):
            self.pending_queries += 1
            if self.pending_queries == 2:
                raise RuntimeError("final broker query failed")
            return super().pending_orders()

    broker = _FinalQueryFailureBroker()
    service = PracticeOrderAcceptanceService(_market(), broker, broker)

    with pytest.raises(
        PracticeAcceptanceError,
        match="final broker query failed",
    ) as error_info:
        service.run(("USD_JPY",))

    assert len(error_info.value.operations) == 3
    assert all(operation.cleaned_up for operation in error_info.value.operations)


@pytest.mark.contract
def test_practice_acceptance_fails_when_cleanup_cannot_be_confirmed():
    broker = _AcceptanceBroker(fail_cleanup=True)
    service = PracticeOrderAcceptanceService(_market(), broker, broker)

    with pytest.raises(PracticeAcceptanceError, match="cleanup"):
        service.run(("USD_JPY",))

    assert broker.pending_orders()


@pytest.mark.contract
def test_practice_acceptance_rejects_untradeable_or_excessive_minimum_units():
    broker = _AcceptanceBroker()

    class _UntradeableMarket:
        def current_quote(self, pair):
            return MarketQuote(pair, 149.9, 150.1, 150.0, False)

    with pytest.raises(PracticeAcceptanceError, match="not tradeable"):
        PracticeOrderAcceptanceService(
            _UntradeableMarket(),
            broker,
            broker,
        ).run(("USD_JPY",))


@pytest.mark.contract
def test_practice_acceptance_preflights_all_pairs_before_first_submit():
    broker = _AcceptanceBroker()

    class _PartiallyTradeableMarket:
        def current_quote(self, pair):
            tradeable = pair == "USD_JPY"
            return MarketQuote(pair, 149.995, 150.005, 150.0, tradeable)

    service = PracticeOrderAcceptanceService(
        _PartiallyTradeableMarket(),
        broker,
        broker,
    )

    with pytest.raises(PracticeAcceptanceError, match="EUR_USD is not tradeable"):
        service.run(("USD_JPY", "EUR_USD"))

    assert broker.requests == []
    assert broker.commands == []


@pytest.mark.contract
def test_practice_acceptance_polls_until_cleanup_is_observable():
    broker = _AcceptanceBroker()
    original_order = broker.order
    checks = {"count": 0}

    def delayed_order(order_id):
        checks["count"] += 1
        if checks["count"] == 2:
            snapshot = original_order(order_id)
            return PositionSnapshot(
                **{
                    **snapshot.__dict__,
                    "order_state": OrderState.PENDING,
                    "life": True,
                }
            )
        return original_order(order_id)

    broker.order = delayed_order
    sleeps = []
    service = PracticeOrderAcceptanceService(
        _market(),
        broker,
        broker,
        poll_attempts=3,
        poll_interval_seconds=0.25,
        sleeper=sleeps.append,
    )

    report = service.run(("USD_JPY",))

    assert report.success is True
    assert sleeps == [0.25]

    broker.instrument_rules = lambda pair: type(
        "Rules",
        (),
        {
            "pair": pair,
            "minimum_trade_size": 10,
            "maximum_order_units": 100,
            "trade_units_precision": 0,
        },
    )()
    with pytest.raises(PracticeAcceptanceError, match="configured safety limit"):
        PracticeOrderAcceptanceService(
            _market(),
            broker,
            broker,
            maximum_units=1,
        ).run(("USD_JPY",))


def _strategy_intent(*, units: int = 7) -> OrderIntent:
    return OrderIntent(
        pair="USD_JPY",
        direction=Direction.SELL,
        order_type=OrderType.LIMIT,
        target=149.5,
        target_is_price=True,
        take_profit=149.0,
        take_profit_is_price=True,
        stop_loss=150.0,
        stop_loss_is_price=True,
        units=units,
        name="strategy-entry",
        priority=1,
        order_timeout_min=7,
        metadata={"source": "matcha"},
    )


@pytest.mark.contract
def test_strategy_acceptance_clamps_only_signed_units_and_preserves_request():
    broker = _AcceptanceBroker()
    broker.instrument_rules = lambda pair: type(
        "Rules",
        (),
        {"pair": pair, "minimum_trade_size": 3, "maximum_order_units": 100, "trade_units_precision": 0},
    )()
    service = PracticeOrderAcceptanceService(
        _market(),
        broker,
        broker,
        maximum_units=10,
        run_id_factory=lambda: "strategy-run",
    )

    report = service.run_strategy_intents(
        (_strategy_intent(),),
        {"USD_JPY": OrderContext(150.0, "2026-08-27T00:00:00+00:00")},
    )

    assert report.success is True
    assert len(broker.requests) == 1
    request = broker.requests[0]
    assert request.units == -3
    assert request.instrument == "USD_JPY"
    assert request.order_type is OrderType.LIMIT
    assert request.price == 149.5
    assert request.take_profit_price == 149.0
    assert request.stop_loss_price == 150.0


@pytest.mark.contract
def test_strategy_acceptance_allows_two_intents_and_submits_both():
    broker = _AcceptanceBroker()
    service = PracticeOrderAcceptanceService(_market(), broker, broker)

    report = service.run_strategy_intents(
        (_strategy_intent(units=2), _strategy_intent(units=4)),
        {"USD_JPY": OrderContext(150.0, "2026-08-27T00:00:00+00:00")},
    )

    assert report.success is True
    assert [request.units for request in broker.requests] == [-1, -1]


@pytest.mark.contract
@pytest.mark.parametrize("count", [0, 3])
def test_strategy_acceptance_rejects_intent_count_before_submit(count):
    broker = _AcceptanceBroker()
    service = PracticeOrderAcceptanceService(_market(), broker, broker)
    intents = tuple(_strategy_intent() for _ in range(count))

    with pytest.raises(PracticeAcceptanceError, match="between 1 and 2"):
        service.run_strategy_intents(
            intents,
            {"USD_JPY": OrderContext(150.0, "2026-08-27T00:00:00+00:00")},
        )

    assert broker.requests == []


@pytest.mark.contract
def test_strategy_acceptance_rejects_invalid_minimum_before_submit():
    broker = _AcceptanceBroker()
    broker.instrument_rules = lambda pair: type(
        "Rules",
        (),
        {"pair": pair, "minimum_trade_size": 11, "maximum_order_units": 100, "trade_units_precision": 0},
    )()
    service = PracticeOrderAcceptanceService(_market(), broker, broker, maximum_units=10)

    with pytest.raises(PracticeAcceptanceError, match="safety limit"):
        service.run_strategy_intents(
            (_strategy_intent(),),
            {"USD_JPY": OrderContext(150.0, "2026-08-27T00:00:00+00:00")},
        )

    assert broker.requests == []


@pytest.mark.contract
def test_strategy_acceptance_evaluates_quote_and_exact_m1_candles_before_workflow():
    broker = _AcceptanceBroker()
    market = _market()
    calls = []

    class _Market:
        def current_quote(self, pair):
            calls.append(("quote", pair))
            quote = market.current_quote(pair)
            return MarketQuote(
                quote.pair,
                quote.bid,
                quote.ask,
                quote.mid,
                quote.tradeable,
                datetime(2026, 8, 27, 0, 0, tzinfo=timezone.utc),
            )

        def candles(self, pair, granularity, count):
            calls.append(("candles", pair, granularity, count))
            return object()

    class _Strategy:
        pair = "USD_JPY"

        def decide(self, input):
            calls.append(("decision", input.quote.source_time, input.evaluation_time, input.positions, input.candles))
            from ogami_oanda.strategy.contracts import StrategyDecision

            return StrategyDecision(intents=(_strategy_intent(),))

    service = PracticeOrderAcceptanceService(_Market(), broker, broker)
    report = service.run_strategy(_Strategy())

    assert report.success is True
    assert calls[0] == ("quote", "USD_JPY")
    assert calls[1] == ("candles", "USD_JPY", "M1", 1000)
    assert calls[2][0] == "decision"
    assert calls[2][1].tzinfo is not None
    assert calls[2][2].tzinfo is not None
    assert calls[2][3] == ()
