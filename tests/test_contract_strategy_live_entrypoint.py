from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from ogami_oanda.application.ports.position_state import (
    CheckpointLoadResult,
    CheckpointLoadStatus,
)
from ogami_oanda.application.services.order_planner import OrderPlanner
from ogami_oanda.application.services.position_portfolio_service import (
    PortfolioStartupState,
    PortfolioSummary,
    PositionPortfolioService,
    RegistrationResult,
    StrategyCommandResult,
)
from ogami_oanda.application.services.position_service import PositionService
from ogami_oanda.domain.orders.models import (
    Direction,
    OrderIntent,
    OrderType,
)
from ogami_oanda.entrypoints import live
from ogami_oanda.infrastructure.config.models import (
    AppSettings,
    RuntimeAccountConfig,
)
from ogami_oanda.strategy.contracts import (
    StrategyCommand,
    StrategyCommandAction,
    StrategyDecision,
)
from tests.fakes import (
    FakeBroker,
    FakeNotifier,
    FixedClock,
    InMemoryTradeHistoryRepository,
)


NOW = datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc)


def _intent(name: str = "matcha-entry") -> OrderIntent:
    return OrderIntent(
        "USD_JPY",
        Direction.BUY,
        OrderType.LIMIT,
        149.9,
        True,
        0.04,
        False,
        0.04,
        False,
        1000,
        name,
        1,
        7,
        metadata={"source": "matcha-oanda"},
    )


class _Market:
    def __init__(self, quote, candles: pd.DataFrame | None = None, trace=None):
        self.quote = quote
        self.frame = candles if candles is not None else pd.DataFrame(
            [{"time": NOW, "open": 150.0, "high": 150.1, "low": 149.9, "close": 150.0}]
        )
        self.trace = trace if trace is not None else []
        self.candle_calls = []
        self.quote_calls = 0

    def current_quote(self, pair):
        self.trace.append("quote")
        self.quote_calls += 1
        assert pair == "USD_JPY"
        return self.quote

    def candles(self, pair, granularity, count):
        self.trace.append("candles")
        self.candle_calls.append((pair, granularity, count))
        return self.frame

    def current_price(self, pair):
        assert pair == "USD_JPY"
        return self.quote.mid


class _Strategy:
    def __init__(self, decision: StrategyDecision, trace=None):
        self.decision = decision
        self.trace = trace if trace is not None else []
        self.state = {"ticks": 0}
        self.load_calls = []
        self.inputs = []

    def load_state(self, state):
        self.trace.append("load_state")
        self.load_calls.append(dict(state))
        self.state = dict(state) if state else {"ticks": 0}

    def dump_state(self):
        return dict(self.state)

    def decide(self, input):
        self.trace.append("decide")
        self.inputs.append(input)
        self.state["ticks"] = int(self.state.get("ticks", 0)) + 1
        return self.decision


class _Portfolio:
    def __init__(
        self,
        trace=None,
        *,
        strategy_state=None,
        startup_state=PortfolioStartupState.READY,
        command_result=None,
        reconcile=True,
    ):
        self.trace = trace if trace is not None else []
        self._strategy_state = dict(strategy_state or {})
        self.startup_state = startup_state
        self.pending_mutations = ()
        self.slots = []
        self.command_result = command_result or StrategyCommandResult()
        self.reconcile_result = reconcile
        self.set_calls = []
        self.sync_calls = []
        self.command_calls = []
        self.registration_calls = []

    @property
    def strategy_state(self):
        return dict(self._strategy_state)

    def reconcile_pending_mutations(self):
        self.trace.append("reconcile")
        return self.reconcile_result

    def sync_all(self, *, current_price=None, dry_run=False):
        self.trace.append("sync")
        self.sync_calls.append((current_price, dry_run))
        return PortfolioSummary(0, 0, 0, 0)

    def set_strategy_checkpoint_state(self, state, *, persist=True):
        self.trace.append("persist_state")
        self._strategy_state = dict(state)
        self.set_calls.append((dict(state), persist))

    def execute_strategy_commands(self, commands, *, dry_run=False):
        self.trace.append("commands")
        self.command_calls.append((commands, dry_run))
        return self.command_result

    def register_plans(self, plans, submit=True):
        self.trace.append("register")
        self.registration_calls.append((tuple(plans), submit))
        return RegistrationResult(tuple(plan.intent.name for plan in plans), ())


class _Planner(OrderPlanner):
    def __init__(self, trace):
        self.trace = trace
        self.calls = []

    def plan(self, intent, context):
        self.trace.append("plan")
        self.calls.append((intent, context))
        return super().plan(intent, context)


class _StateRepository:
    def __init__(self):
        self.saved = []

    def load(self, **_kwargs):
        return CheckpointLoadResult(CheckpointLoadStatus.MISSING)

    def save(self, checkpoint):
        self.saved.append(checkpoint)


def _strategy_application(*args, **kwargs):
    implementation = getattr(live, "StrategyLiveApplication", None)
    assert implementation is not None, "StrategyLiveApplication is not implemented"
    return implementation(*args, **kwargs)


@pytest.mark.contract
def test_strategy_loads_restored_state_once_before_first_decision_and_does_not_restart_duplicate():
    trace = []
    market = _Market(
        live.MarketQuote("USD_JPY", 149.99, 150.0, 149.995, True, NOW),
        trace=trace,
    )

    class _NoDuplicateStrategy(_Strategy):
        def decide(self, input):
            self.trace.append("decide")
            self.inputs.append(input)
            duplicate = self.state.get("last_candle") == "2026-01-02T03:04:00+00:00"
            self.state["last_candle"] = "2026-01-02T03:04:00+00:00"
            return StrategyDecision(intents=() if duplicate else (_intent(),))

    strategy = _NoDuplicateStrategy(StrategyDecision(), trace)
    portfolio = _Portfolio(
        trace,
        strategy_state={"last_candle": "2026-01-02T03:04:00+00:00"},
    )
    application = _strategy_application(
        "USD_JPY",
        strategy,
        "plugin-id",
        market,
        OrderPlanner(),
        portfolio,
        FixedClock(NOW),
        startup=lambda: trace.append("startup"),
    )

    first = application.run_once(now=NOW)
    second = application.run_once(now=NOW + timedelta(seconds=1))

    assert strategy.load_calls == [
        {"last_candle": "2026-01-02T03:04:00+00:00"}
    ]
    assert first.plans == ()
    assert second.plans == ()
    assert trace.index("load_state") < trace.index("decide")


@pytest.mark.contract
def test_strategy_tick_fetches_one_newest_first_m1_frame_and_plans_then_registers_each_intent():
    trace = []
    frame = pd.DataFrame(
        [
            {"time": "2026-01-02T03:04:00+00:00", "close": 150.0},
            {"time": "2026-01-02T03:03:00+00:00", "close": 149.9},
        ]
    )
    market = _Market(
        live.MarketQuote("USD_JPY", 149.99, 150.0, 149.995, True, NOW),
        frame,
        trace,
    )
    strategy = _Strategy(StrategyDecision(intents=(_intent(),)), trace)
    portfolio = _Portfolio(trace)
    planner = _Planner(trace)
    application = _strategy_application(
        "USD_JPY",
        strategy,
        "plugin-id",
        market,
        planner,
        portfolio,
        FixedClock(NOW),
    )

    result = application.run_once(now=NOW, decision_time="decision-id")

    assert market.quote_calls == 1
    assert market.candle_calls == [("USD_JPY", "M1", 1000)]
    assert len(strategy.inputs) == 1
    assert strategy.inputs[0].candles is frame
    assert strategy.inputs[0].evaluation_time == NOW
    assert planner.calls[0][1].current_price == pytest.approx(149.995)
    assert planner.calls[0][1].decision_time == "decision-id"
    assert len(result.plans) == 1
    assert result.plans[0].intent.name == "matcha-entry"
    assert portfolio.registration_calls == [((result.plans[0],), True)]
    assert trace.index("commands") < trace.index("plan") < trace.index("register")
    assert trace.index("persist_state") < trace.index("commands")


@pytest.mark.contract
@pytest.mark.parametrize(
    "command_result",
    [
        StrategyCommandResult(rejected=("broker_rejected",)),
        StrategyCommandResult(unresolved=True),
    ],
)
def test_strategy_command_failure_suppresses_all_planning_and_registration(command_result):
    trace = []
    command = StrategyCommand(
        StrategyCommandAction.CANCEL_PENDING,
        "matcha-oanda",
        "risk",
    )
    strategy = _Strategy(
        StrategyDecision(commands=(command,), intents=(_intent(),)),
        trace,
    )
    portfolio = _Portfolio(trace, command_result=command_result)
    planner = _Planner(trace)
    application = _strategy_application(
        "USD_JPY",
        strategy,
        "plugin-id",
        _Market(live.MarketQuote("USD_JPY", 149.99, 150.0, 149.995, True, NOW)),
        planner,
        portfolio,
        FixedClock(NOW),
    )

    result = application.run_once(now=NOW)

    assert result.plans == ()
    assert result.registration == RegistrationResult((), ())
    assert planner.calls == []
    assert portfolio.registration_calls == []
    assert result.strategy_command_result == command_result


@pytest.mark.contract
@pytest.mark.parametrize(
    ("quote", "expected_skip"),
    [
        (
            live.MarketQuote("USD_JPY", 149.98, 150.02, 150.0, True, NOW),
            "wide_spread",
        ),
        (
            live.MarketQuote("USD_JPY", 149.99, 150.0, 149.995, False, NOW),
            "quote_untradeable",
        ),
        (
            live.MarketQuote(
                "USD_JPY",
                149.99,
                150.0,
                149.995,
                True,
                NOW - timedelta(seconds=3),
            ),
            "stale_quote",
        ),
        (
            live.MarketQuote("USD_JPY", 149.99, 150.0, 149.995, True, None),
            "stale_quote",
        ),
    ],
)
def test_strategy_risk_commands_run_while_unsafe_quotes_suppress_new_intents(
    quote,
    expected_skip,
):
    command = StrategyCommand(
        StrategyCommandAction.CLOSE_ALL,
        "matcha-oanda",
        "emergency",
    )
    strategy = _Strategy(
        StrategyDecision(commands=(command,), intents=(_intent(),))
    )
    portfolio = _Portfolio()
    planner = _Planner([])
    application = _strategy_application(
        "USD_JPY",
        strategy,
        "plugin-id",
        _Market(quote),
        planner,
        portfolio,
        FixedClock(NOW),
    )

    result = application.run_once(now=NOW)

    assert portfolio.command_calls == [((command,), False)]
    assert result.strategy_decision is strategy.decision
    assert result.plans == ()
    assert portfolio.registration_calls == []
    assert expected_skip in result.skipped


@pytest.mark.contract
def test_strategy_quote_age_uses_strategy_configured_latency_when_available():
    class _ConfiguredStrategy(_Strategy):
        class Config:
            max_latency_ms = 1900

        config = Config()

    strategy = _ConfiguredStrategy(StrategyDecision(intents=(_intent(),)))
    portfolio = _Portfolio()
    application = _strategy_application(
        "USD_JPY",
        strategy,
        "plugin-id",
        _Market(
            live.MarketQuote(
                "USD_JPY",
                149.99,
                150.0,
                149.995,
                True,
                NOW - timedelta(milliseconds=1950),
            )
        ),
        OrderPlanner(),
        portfolio,
        FixedClock(NOW),
    )

    result = application.run_once(now=NOW)

    assert result.plans == ()
    assert "stale_quote" in result.skipped
    assert portfolio.registration_calls == []


@pytest.mark.contract
def test_strategy_noop_decision_persists_advanced_state():
    broker = FakeBroker()
    repository = _StateRepository()
    position_service = PositionService(
        broker,
        broker,
        FakeNotifier(),
        InMemoryTradeHistoryRepository(),
        FixedClock(NOW),
    )
    portfolio = PositionPortfolioService(
        "USD_JPY",
        position_service,
        broker,
        broker,
        state_repository=repository,
        account_hash="account-hash",
        strategy_id="plugin-id",
    )
    strategy = _Strategy(StrategyDecision())
    application = _strategy_application(
        "USD_JPY",
        strategy,
        "plugin-id",
        _Market(live.MarketQuote("USD_JPY", 149.99, 150.0, 149.995, True, NOW)),
        OrderPlanner(),
        portfolio,
        FixedClock(NOW),
        startup=portfolio.restore_and_reconcile,
    )

    result = application.run_once(now=NOW)

    assert result.plans == ()
    assert repository.saved[-1].strategy_state == {"ticks": 1}
    assert portfolio.strategy_state == {"ticks": 1}


@pytest.mark.contract
def test_strategy_dry_run_is_repeatable_without_broker_repository_or_portfolio_effects():
    broker = FakeBroker()
    repository = _StateRepository()
    position_service = PositionService(
        broker,
        broker,
        FakeNotifier(),
        InMemoryTradeHistoryRepository(),
        FixedClock(NOW),
    )
    portfolio = PositionPortfolioService(
        "USD_JPY",
        position_service,
        broker,
        broker,
        state_repository=repository,
        account_hash="account-hash",
        state_writable=False,
        strategy_id="plugin-id",
    )
    portfolio.startup_state = PortfolioStartupState.READY
    portfolio.set_strategy_checkpoint_state({"ticks": 4}, persist=False)
    command = StrategyCommand(
        StrategyCommandAction.CANCEL_PENDING,
        "matcha-oanda",
        "preview",
    )
    strategy = _Strategy(
        StrategyDecision(commands=(command,), intents=(_intent(),))
    )
    application = _strategy_application(
        "USD_JPY",
        strategy,
        "plugin-id",
        _Market(live.MarketQuote("USD_JPY", 149.99, 150.0, 149.995, True, NOW)),
        OrderPlanner(),
        portfolio,
        FixedClock(NOW),
    )
    slots_before = tuple(portfolio.slots)
    journal_before = portfolio.pending_mutations

    first = application.run_once(now=NOW, dry_run=True)
    second = application.run_once(now=NOW, dry_run=True)

    assert tuple(plan.broker_request for plan in first.plans) == tuple(
        plan.broker_request for plan in second.plans
    )
    assert first.strategy_decision is strategy.decision
    assert first.strategy_command_result is not None
    assert strategy.dump_state() == {"ticks": 4}
    assert portfolio.strategy_state == {"ticks": 4}
    assert tuple(portfolio.slots) == slots_before
    assert portfolio.pending_mutations == journal_before
    assert repository.saved == []
    assert broker.requests == []
    assert broker.commands == []


@pytest.mark.contract
def test_strategy_dry_run_restores_nested_json_state_without_aliasing():
    class _NestedStateStrategy(_Strategy):
        def __init__(self):
            super().__init__(StrategyDecision())
            self.state = {"latencies": [1.0, 2.0]}

        def decide(self, input):
            self.inputs.append(input)
            self.state["latencies"].append(3.0)
            return self.decision

    strategy = _NestedStateStrategy()
    portfolio = _Portfolio(strategy_state={"latencies": [1.0, 2.0]})
    application = _strategy_application(
        "USD_JPY",
        strategy,
        "plugin-id",
        _Market(live.MarketQuote("USD_JPY", 149.99, 150.0, 149.995, True, NOW)),
        OrderPlanner(),
        portfolio,
        FixedClock(NOW),
    )

    application.run_once(now=NOW, dry_run=True)

    assert strategy.dump_state() == {"latencies": [1.0, 2.0]}


@pytest.mark.contract
@pytest.mark.parametrize(
    ("startup_state", "reconcile", "expected_skip"),
    [
        (PortfolioStartupState.QUARANTINED, True, "portfolio_quarantined"),
        (PortfolioStartupState.READY, False, "broker_reconciliation"),
    ],
)
def test_strategy_startup_safety_gates_before_market_and_decision(
    startup_state,
    reconcile,
    expected_skip,
):
    market = _Market(live.MarketQuote("USD_JPY", 149.99, 150.0, 149.995, True, NOW))
    strategy = _Strategy(StrategyDecision())
    portfolio = _Portfolio(startup_state=startup_state, reconcile=reconcile)
    application = _strategy_application(
        "USD_JPY",
        strategy,
        "plugin-id",
        market,
        OrderPlanner(),
        portfolio,
        FixedClock(NOW),
    )

    result = application.run_once(now=NOW)

    assert result.skipped == (expected_skip,)
    assert market.quote_calls == 0
    assert strategy.inputs == []


@pytest.mark.contract
def test_build_strategy_live_application_preserves_account_checks_and_selects_plugin_identity():
    builder = getattr(live, "build_strategy_live_application", None)
    assert builder is not None, "build_strategy_live_application is not implemented"
    settings = AppSettings(
        accounts={
            "primary": RuntimeAccountConfig(
                account_id="id",
                access_token="token",
                environment="practice",
            )
        }
    )
    broker = FakeBroker(account_id="id")
    repository = _StateRepository()
    strategy = _Strategy(StrategyDecision())

    application = builder(
        settings,
        strategy,
        "plugin-id",
        market_data=_Market(
            live.MarketQuote("USD_JPY", 149.99, 150.0, 149.995, True, NOW)
        ),
        broker_execution=broker,
        broker_query=broker,
        notifier=FakeNotifier(),
        history=InMemoryTradeHistoryRepository(),
        state_repository=repository,
        clock=FixedClock(NOW),
    )

    assert isinstance(application, live.StrategyLiveApplication)
    assert application.portfolio.strategy_id == "plugin-id"
    assert repository.saved[-1].strategy_id == "plugin-id"


@pytest.mark.contract
def test_live_run_result_keeps_strategy_reporting_fields_backward_compatible():
    result = live.LiveRunResult(None, RegistrationResult((), ()))

    assert result.strategy_decision is None
    assert result.strategy_command_result is None
