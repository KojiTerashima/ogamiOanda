from datetime import datetime, timedelta

import pytest

from ogami_oanda.application.services.market_analysis_service import (
    MarketAnalysisResult,
)
from ogami_oanda.application.services.order_planner import OrderPlanner
from ogami_oanda.application.services.position_portfolio_service import (
    PortfolioStartupState,
    PortfolioSummary,
    PositionPortfolioService,
    RegistrationResult,
)
from ogami_oanda.application.services.position_service import PositionService
from ogami_oanda.application.services.runtime_event_buffer import RuntimeEventBuffer
from ogami_oanda.application.errors import TransientExternalServiceError
from ogami_oanda.domain.orders.models import (
    Direction,
    OrderContext,
    OrderIntent,
    OrderType,
)
from ogami_oanda.domain.positions.models import OrderState, PositionSnapshot, TradeState
from ogami_oanda.entrypoints.live import LiveApplication, build_live_application
from ogami_oanda.application.ports.market_data import MarketQuote
from ogami_oanda.infrastructure.config.models import AppSettings, RuntimeAccountConfig
from tests.fakes import (
    FakeBroker,
    FakeMarketData,
    FakeNotifier,
    FixedClock,
    InMemoryTradeHistoryRepository,
)


class _MissingStateRepository:
    def __init__(self):
        self.saved = []

    def load(self, **_kwargs):
        from ogami_oanda.application.ports.position_state import (
            CheckpointLoadResult,
            CheckpointLoadStatus,
        )

        return CheckpointLoadResult(CheckpointLoadStatus.MISSING)

    def save(self, checkpoint):
        self.saved.append(checkpoint)


class _Analysis:
    def __init__(self, intent):
        self.intent = intent

    def analyze(self, pair, decision_time, *, current_price=None):
        return MarketAnalysisResult((self.intent,), {}, {})


class _NoAnalysis:
    def __init__(self):
        self.calls = 0

    def analyze(self, pair, decision_time, *, current_price=None):
        self.calls += 1
        return MarketAnalysisResult((), {}, {})


class _WideSpreadMarket(FakeMarketData):
    def current_quote(self, pair):
        mid = self.current_price(pair)
        return MarketQuote(pair, mid - 0.01, mid + 0.01, mid)


class _TracingMarket:
    def __init__(self, trace, quote):
        self.trace = trace
        self.quote = quote
        self.calls = 0

    def current_quote(self, pair):
        self.calls += 1
        self.trace.append("quote")
        assert pair == self.quote.pair
        return self.quote


class _TracingAnalysis:
    def __init__(self, trace):
        self.trace = trace
        self.calls = []

    def analyze(self, pair, decision_time, *, current_price=None):
        self.trace.append("analysis")
        self.calls.append((pair, decision_time, current_price))
        return MarketAnalysisResult((), {}, {})


class _TracingPortfolio:
    def __init__(self, trace):
        self.trace = trace
        self.sync_calls = []
        self.registration_calls = []

    def sync_all(self, *, current_price=None, dry_run=False):
        self.trace.append("sync")
        self.sync_calls.append((current_price, dry_run))
        return None

    def register_plans(self, plans, submit=True):
        self.trace.append("register")
        self.registration_calls.append((plans, submit))
        return type("_Registration", (), {"accepted": (), "rejected": ()})()


@pytest.mark.contract
def test_live_run_once_dry_run_registers_watching_position_without_submission():
    clock = FixedClock(datetime(2026, 1, 2, 3, 4, 5))
    broker = FakeBroker()
    position_service = PositionService(broker, broker, FakeNotifier(), InMemoryTradeHistoryRepository(), clock)
    portfolio = PositionPortfolioService("USD_JPY", position_service, broker, broker)
    intent = OrderIntent("USD_JPY", Direction.BUY, OrderType.LIMIT, 150.0, True, 10, False, 10, False, 1000, "line", 1, 0)
    application = LiveApplication("USD_JPY", FakeMarketData({}, {"USD_JPY": 150.2}), _Analysis(intent), OrderPlanner(), portfolio, clock)

    result = application.run_once(dry_run=True)

    assert result.registration.accepted == ("line",)
    assert broker.requests == []
    assert portfolio.summary().watching == 1


@pytest.mark.contract
def test_registration_rejection_is_exposed_as_runtime_event():
    clock = FixedClock(datetime(2026, 1, 2, 3, 4, 5))
    broker = FakeBroker()
    position_service = PositionService(
        broker,
        broker,
        FakeNotifier(),
        InMemoryTradeHistoryRepository(),
        clock,
    )
    runtime_events = RuntimeEventBuffer()
    position_service.set_event_sink(runtime_events.publish)
    portfolio = PositionPortfolioService("USD_JPY", position_service, broker, broker)
    intent = OrderIntent(
        "EUR_USD",
        Direction.BUY,
        OrderType.LIMIT,
        1.0,
        True,
        10,
        False,
        10,
        False,
        1000,
        "wrong-pair",
        1,
        0,
    )
    plan = OrderPlanner().plan(intent, OrderContext(1.0, "2026/01/02 03:04:05"))

    registration = portfolio.register_plans([plan], submit=True)

    assert registration.rejected == (("wrong-pair", "pair_mismatch"),)
    assert [event.kind for event in runtime_events.drain()] == ["order_rejected"]


@pytest.mark.contract
def test_live_planner_preserves_analysis_order_context_for_reporting():
    clock = FixedClock(datetime(2026, 1, 2, 3, 4, 5))
    broker = FakeBroker()
    position_service = PositionService(
        broker,
        broker,
        FakeNotifier(),
        InMemoryTradeHistoryRepository(),
        clock,
    )
    portfolio = PositionPortfolioService(
        "USD_JPY",
        position_service,
        broker,
        broker,
    )
    intent = OrderIntent(
        "USD_JPY",
        Direction.BUY,
        OrderType.LIMIT,
        150.0,
        True,
        10,
        False,
        10,
        False,
        1000,
        "line",
        1,
        0,
    )
    analysis_context = OrderContext(
        current_price=150.2,
        decision_time="2026/01/02 03:00:00",
        move_average=0.045,
    )

    class _ContextAnalysis:
        def analyze(self, pair, decision_time, *, current_price=None):
            return MarketAnalysisResult(
                (intent,),
                {},
                {},
                order_context=analysis_context,
            )

    application = LiveApplication(
        "USD_JPY",
        FakeMarketData({}, {"USD_JPY": 150.2}),
        _ContextAnalysis(),
        OrderPlanner(),
        portfolio,
        clock,
    )

    result = application.run_once(
        dry_run=True,
        decision_time="2026-01-02T03:04:05",
    )

    assert len(result.plans) == 1
    assert result.plans[0].context is analysis_context
    assert result.plans[0].context.decision_time == "2026/01/02 03:00:00"
    assert result.plans[0].context.move_average == pytest.approx(0.045)


@pytest.mark.contract
def test_live_schedule_runs_initial_analysis_then_five_minute_analysis_and_two_second_sync():
    trace = []
    market = _TracingMarket(trace, MarketQuote("USD_JPY", 150.0, 150.0, 150.0))
    analysis = _TracingAnalysis(trace)
    portfolio = _TracingPortfolio(trace)
    application = LiveApplication(
        "USD_JPY",
        market,
        analysis,
        OrderPlanner(),
        portfolio,
        FixedClock(datetime(2026, 1, 2)),
    )

    initial = application.run_once(
        now=datetime(2026, 1, 2, 10, 1, 4),
        dry_run=True,
    )
    assert initial.analysis is not None
    assert trace == ["quote", "analysis", "register"]

    trace.clear()
    between_windows = application.run_once(
        now=datetime(2026, 1, 2, 10, 2, 2),
        dry_run=True,
    )
    assert between_windows.analysis is None
    assert trace == ["quote", "sync"]

    trace.clear()
    scheduled = application.run_once(
        now=datetime(2026, 1, 2, 10, 5, 6),
        dry_run=True,
    )
    assert scheduled.analysis is not None
    assert trace == ["quote", "sync", "analysis", "register", "sync"]
    assert market.calls == 3
    assert portfolio.sync_calls == [
        (150.0, True),
        (150.0, True),
        (150.0, True),
    ]
    assert len(analysis.calls) == 2


@pytest.mark.contract
def test_live_composition_never_cancels_unmanaged_pending_on_start(candle_frame):
    settings = AppSettings({"primary": RuntimeAccountConfig("id", "token", "practice")})
    broker = FakeBroker()
    market = FakeMarketData({("USD_JPY", "M5"): candle_frame}, {"USD_JPY": 150.0})

    build_live_application(settings, market_data=market, broker_execution=broker, broker_query=broker, notifier=FakeNotifier(), history=InMemoryTradeHistoryRepository(), state_repository=_MissingStateRepository(), clock=FixedClock(datetime(2026, 1, 2)))
    assert broker.commands == []

    broker.orders["pending-1"] = PositionSnapshot("pending", "USD_JPY", OrderState.PENDING, TradeState.NONE, order_id="pending-1")
    application = build_live_application(settings, market_data=market, broker_execution=broker, broker_query=broker, notifier=FakeNotifier(), history=InMemoryTradeHistoryRepository(), state_repository=_MissingStateRepository(), clock=FixedClock(datetime(2026, 1, 2)), cancel_pending_on_start=True)
    assert broker.commands == []
    assert application.portfolio.startup_state is PortfolioStartupState.QUARANTINED

    dry_broker = FakeBroker()
    dry_broker.orders["pending-2"] = PositionSnapshot(
        "pending",
        "USD_JPY",
        OrderState.PENDING,
        TradeState.NONE,
        order_id="pending-2",
    )
    build_live_application(
        settings,
        market_data=market,
        broker_execution=dry_broker,
        broker_query=dry_broker,
        notifier=FakeNotifier(),
        history=InMemoryTradeHistoryRepository(),
        clock=FixedClock(datetime(2026, 1, 2)),
        cancel_pending_on_start=True,
        dry_run=True,
    )
    assert dry_broker.requests == []
    assert dry_broker.commands == []


@pytest.mark.contract
def test_live_scheduler_skips_sunday_without_requesting_a_quote():
    class _NoQuote:
        def current_quote(self, pair):
            raise AssertionError("Sunday must not query pricing")

    clock = FixedClock(datetime(2026, 1, 4, 10, 0, 0))
    broker = FakeBroker()
    service = PositionService(broker, broker, FakeNotifier(), InMemoryTradeHistoryRepository(), clock)
    application = LiveApplication("USD_JPY", _NoQuote(), _NoAnalysis(), OrderPlanner(), PositionPortfolioService("USD_JPY", service, broker, broker), clock)

    result = application.run_once()

    assert result.skipped == ("market_closed",)
    assert broker.requests == []
    assert broker.commands == []


@pytest.mark.contract
@pytest.mark.parametrize(
    "now",
    [
        datetime(2026, 1, 3, 4, 0, 0),
        datetime(2026, 1, 5, 7, 59, 59),
    ],
)
def test_live_scheduler_updates_each_tick_in_weekend_transition_without_analysis(now):
    trace = []
    market = _TracingMarket(trace, MarketQuote("USD_JPY", 150.0, 150.0, 150.0))
    analysis = _TracingAnalysis(trace)
    portfolio = _TracingPortfolio(trace)
    application = LiveApplication(
        "USD_JPY",
        market,
        analysis,
        OrderPlanner(),
        portfolio,
        FixedClock(now),
    )

    # Legacy initializes once even inside the update-only window.
    initial = application.run_once(now=now - timedelta(seconds=1), dry_run=True)
    assert initial.analysis is not None
    assert trace == ["quote", "analysis", "register"]
    trace.clear()
    result = application.run_once(now=now, dry_run=True)

    assert result.analysis is None
    assert result.skipped == ("update_only",)
    assert trace == ["quote", "sync"]
    assert len(analysis.calls) == 1


@pytest.mark.contract
def test_live_scheduler_uses_update_only_for_wide_spread_and_dry_run_has_no_commands():
    clock = FixedClock(datetime(2026, 1, 2, 10, 1, 3))
    broker = FakeBroker()
    service = PositionService(broker, broker, FakeNotifier(), InMemoryTradeHistoryRepository(), clock)
    analysis = _NoAnalysis()
    market = _WideSpreadMarket({}, {"USD_JPY": 150.0})
    application = LiveApplication("USD_JPY", market, analysis, OrderPlanner(), PositionPortfolioService("USD_JPY", service, broker, broker), clock)

    initial = application.run_once(
        now=datetime(2026, 1, 2, 10, 1, 2),
        dry_run=True,
    )
    result = application.run_once(dry_run=True)

    assert initial.analysis is not None
    assert result.skipped == ("update_only",)
    assert analysis.calls == 1
    assert broker.requests == []
    assert broker.commands == []


@pytest.mark.contract
def test_live_run_forever_accepts_finite_ticks_without_sleeping():
    clock = FixedClock(datetime(2026, 1, 2, 10, 0, 0))
    broker = FakeBroker()
    service = PositionService(broker, broker, FakeNotifier(), InMemoryTradeHistoryRepository(), clock)
    application = LiveApplication("USD_JPY", FakeMarketData({}, {"USD_JPY": 150.0}), _NoAnalysis(), OrderPlanner(), PositionPortfolioService("USD_JPY", service, broker, broker), clock)

    results = application.run_forever(dry_run=True, sleeper=lambda seconds: (_ for _ in ()).throw(AssertionError("must not sleep after final tick")), max_ticks=1)

    assert len(results) == 1
    assert broker.requests == []
    assert broker.commands == []


@pytest.mark.contract
def test_live_runner_recovers_from_transient_read_failure_and_resets_backoff():
    class _FlakyMarket:
        def __init__(self):
            self.calls = 0

        def current_quote(self, pair):
            self.calls += 1
            if self.calls in {1, 3}:
                raise TransientExternalServiceError("oanda", "temporary outage")
            return MarketQuote(pair, 150.0, 150.0, 150.0)

    clock = FixedClock(datetime(2026, 1, 2, 10, 0, 0))
    broker = FakeBroker()
    service = PositionService(
        broker,
        broker,
        FakeNotifier(),
        InMemoryTradeHistoryRepository(),
        clock,
    )
    market = _FlakyMarket()
    application = LiveApplication(
        "USD_JPY",
        market,
        _NoAnalysis(),
        OrderPlanner(),
        PositionPortfolioService("USD_JPY", service, broker, broker),
        clock,
    )

    def advance(_seconds):
        clock.value += timedelta(seconds=1)

    results = application.run_forever(
        dry_run=True,
        sleeper=advance,
        max_ticks=4,
    )

    assert [result.skipped for result in results] == [
        ("broker_unavailable",),
        (),
        ("broker_unavailable",),
        ("outside_sync_window",),
    ]
    assert market.calls == 4


@pytest.mark.contract
def test_live_composition_retries_transient_startup_inside_resilient_loop():
    class _FlakyStartupBroker(FakeBroker):
        def __init__(self):
            super().__init__()
            self.capability_calls = 0

        def account_capabilities(self):
            self.capability_calls += 1
            if self.capability_calls <= 2:
                raise TransientExternalServiceError(
                    "oanda",
                    "temporary startup outage",
                )
            return super().account_capabilities()

    clock = FixedClock(datetime(2026, 1, 4, 10, 0, 0))
    broker = _FlakyStartupBroker()
    application = build_live_application(
        AppSettings(
            {"primary": RuntimeAccountConfig("id", "token", "practice")}
        ),
        market_data=FakeMarketData({}, {"USD_JPY": 150.0}),
        broker_execution=broker,
        broker_query=broker,
        notifier=FakeNotifier(),
        history=InMemoryTradeHistoryRepository(),
        state_repository=_MissingStateRepository(),
        clock=clock,
        dry_run=True,
    )

    results = application.run_forever(
        dry_run=True,
        sleeper=lambda seconds: setattr(
            clock,
            "value",
            clock.value + timedelta(seconds=seconds),
        ),
        max_ticks=3,
    )

    assert [result.skipped for result in results] == [
        ("broker_unavailable",),
        ("broker_backoff",),
        ("market_closed",),
    ]
    assert broker.capability_calls == 4


@pytest.mark.contract
def test_live_runner_honors_retry_after_without_broker_calls():
    class _RateLimitedMarket:
        def __init__(self):
            self.calls = 0

        def current_quote(self, pair):
            self.calls += 1
            raise TransientExternalServiceError(
                "oanda",
                "rate limited",
                retry_after_seconds=5,
            )

    clock = FixedClock(datetime(2026, 1, 2, 10, 0, 0))
    broker = FakeBroker()
    service = PositionService(
        broker,
        broker,
        FakeNotifier(),
        InMemoryTradeHistoryRepository(),
        clock,
    )
    market = _RateLimitedMarket()
    application = LiveApplication(
        "USD_JPY",
        market,
        _NoAnalysis(),
        OrderPlanner(),
        PositionPortfolioService("USD_JPY", service, broker, broker),
        clock,
    )

    results = application.run_forever(
        dry_run=True,
        sleeper=lambda seconds: setattr(
            clock,
            "value",
            clock.value + timedelta(seconds=seconds),
        ),
        max_ticks=3,
    )

    assert results[0].skipped == ("broker_unavailable",)
    assert results[1].skipped == ("broker_backoff",)
    assert results[2].skipped == ("broker_backoff",)
    assert market.calls == 1


@pytest.mark.contract
def test_live_runner_keeps_unknown_programming_errors_fail_fast():
    class _BrokenMarket:
        def current_quote(self, pair):
            del pair
            raise ValueError("programming defect")

    broker = FakeBroker()
    clock = FixedClock(datetime(2026, 1, 2, 10, 0, 0))
    service = PositionService(
        broker,
        broker,
        FakeNotifier(),
        InMemoryTradeHistoryRepository(),
        clock,
    )
    application = LiveApplication(
        "USD_JPY",
        _BrokenMarket(),
        _NoAnalysis(),
        OrderPlanner(),
        PositionPortfolioService("USD_JPY", service, broker, broker),
        clock,
    )

    with pytest.raises(ValueError, match="programming defect"):
        application.run_forever(
            dry_run=True,
            sleeper=lambda _seconds: None,
            max_ticks=1,
        )


@pytest.mark.contract
@pytest.mark.parametrize(
    ("pair", "mid"),
    [
        ("USD_JPY", 150.0),
        ("EUR_USD", 1.1),
        ("AUD_USD", 0.65),
    ],
)
def test_three_pair_live_dry_run_uses_same_finite_composition(pair, mid):
    clock = FixedClock(datetime(2026, 1, 2, 10, 1, 5))
    broker = FakeBroker()
    service = PositionService(
        broker,
        broker,
        FakeNotifier(),
        InMemoryTradeHistoryRepository(),
        clock,
    )
    analysis = _NoAnalysis()
    application = LiveApplication(
        pair,
        FakeMarketData({}, {pair: mid}),
        analysis,
        OrderPlanner(),
        PositionPortfolioService(pair, service, broker, broker),
        clock,
    )

    results = application.run_forever(
        dry_run=True,
        sleeper=lambda seconds: (_ for _ in ()).throw(
            AssertionError("one finite tick must not sleep")
        ),
        max_ticks=1,
    )

    assert len(results) == 1
    assert results[0].analysis is not None
    assert results[0].quote == MarketQuote(pair, mid, mid, mid)
    assert analysis.calls == 1
    assert broker.requests == []
    assert broker.commands == []


@pytest.mark.contract
@pytest.mark.parametrize(
    ("pair", "mid", "spread"),
    [
        ("USD_JPY", 150.0, 0.012),
        ("EUR_USD", 1.1, 0.00016),
        ("AUD_USD", 0.65, 0.00019),
    ],
)
def test_three_pair_spread_limits_switch_live_tick_to_update_only(pair, mid, spread):
    trace = []
    market = _TracingMarket(
        trace,
        MarketQuote(pair, mid, mid + spread, mid + spread / 2),
    )
    analysis = _TracingAnalysis(trace)
    portfolio = _TracingPortfolio(trace)
    application = LiveApplication(
        pair,
        market,
        analysis,
        OrderPlanner(),
        portfolio,
        FixedClock(datetime(2026, 1, 2, 10, 1, 5)),
    )

    initial = application.run_once(
        now=datetime(2026, 1, 2, 10, 1, 4),
        dry_run=True,
    )
    assert initial.analysis is not None
    assert trace == ["quote", "analysis", "register"]
    trace.clear()

    result = application.run_once(
        now=datetime(2026, 1, 2, 10, 1, 5),
        dry_run=True,
    )

    assert result.analysis is None
    assert result.skipped == ("update_only",)
    assert trace == ["quote", "sync"]


@pytest.mark.contract
def test_live_composition_shares_one_oanda_client_across_all_broker_adapters(monkeypatch):
    import ogami_oanda.entrypoints.live as live

    clients = []

    class _Client:
        def __init__(self, account):
            self.account = account
            clients.append(self)

    class _Market:
        def __init__(self, client):
            self.client = client

    class _Execution:
        def __init__(self, client):
            self.client = client

    class _Query:
        def __init__(self, client):
            self.client = client

        def account_capabilities(self):
            from ogami_oanda.application.ports.broker import AccountCapabilities

            return AccountCapabilities("id", True)

        def open_positions(self):
            return []

        def pending_orders(self):
            return []

    monkeypatch.setattr(live, "OandaClient", _Client)
    monkeypatch.setattr(live, "OandaMarketDataAdapter", _Market)
    monkeypatch.setattr(live, "OandaExecutionAdapter", _Execution)
    monkeypatch.setattr(live, "OandaQueryAdapter", _Query)
    settings = AppSettings({"primary": RuntimeAccountConfig("id", "token", "practice")})

    application = build_live_application(
        settings,
        notifier=FakeNotifier(),
        history=InMemoryTradeHistoryRepository(),
        state_repository=_MissingStateRepository(),
        clock=FixedClock(datetime(2026, 1, 2)),
    )

    assert len(clients) == 1
    assert application.market_data.client is clients[0]
    assert application.portfolio.broker_execution.client is clients[0]
    assert application.portfolio.broker_query.client is clients[0]


@pytest.mark.contract
def test_live_composition_fails_closed_when_required_hedging_is_disabled(candle_frame):
    settings = AppSettings(
        {"primary": RuntimeAccountConfig("id", "token", "practice")}
    )
    broker = FakeBroker(hedging_enabled=False)
    market = FakeMarketData(
        {("USD_JPY", "M5"): candle_frame},
        {"USD_JPY": 150.0},
    )

    with pytest.raises(ValueError, match="hedging enabled"):
        build_live_application(
            settings,
            market_data=market,
            broker_execution=broker,
            broker_query=broker,
            notifier=FakeNotifier(),
            history=InMemoryTradeHistoryRepository(),
            clock=FixedClock(datetime(2026, 1, 2)),
        )

    assert broker.requests == []
    assert broker.commands == []


@pytest.mark.contract
def test_non_dry_live_composition_requires_runtime_checkpoint(candle_frame):
    settings = AppSettings(
        {"primary": RuntimeAccountConfig("id", "token", "practice")}
    )
    broker = FakeBroker()

    with pytest.raises(ValueError, match="position state repository"):
        build_live_application(
            settings,
            market_data=FakeMarketData(
                {("USD_JPY", "M5"): candle_frame},
                {"USD_JPY": 150.0},
            ),
            broker_execution=broker,
            broker_query=broker,
            notifier=FakeNotifier(),
            history=InMemoryTradeHistoryRepository(),
            clock=FixedClock(datetime(2026, 1, 2)),
        )

    assert broker.requests == []
    assert broker.commands == []


@pytest.mark.contract
def test_live_environment_requires_explicit_opt_in_but_allows_dry_run(candle_frame):
    settings = AppSettings(
        {"primary": RuntimeAccountConfig("id", "token", "live")}
    )
    broker = FakeBroker()
    market = FakeMarketData(
        {("USD_JPY", "M5"): candle_frame},
        {"USD_JPY": 150.0},
    )
    dependencies = {
        "market_data": market,
        "broker_execution": broker,
        "broker_query": broker,
        "notifier": FakeNotifier(),
        "history": InMemoryTradeHistoryRepository(),
        "clock": FixedClock(datetime(2026, 1, 2)),
    }

    with pytest.raises(ValueError, match="live trading opt-in"):
        build_live_application(settings, **dependencies)

    application = build_live_application(settings, dry_run=True, **dependencies)
    assert application.pair == "USD_JPY"


@pytest.mark.contract
def test_live_run_once_skips_market_and_analysis_when_portfolio_is_quarantined():
    class _NoMarket:
        def current_quote(self, pair):
            raise AssertionError("quarantined portfolio must not query market data")

    analysis = _NoAnalysis()
    broker = FakeBroker()
    service = PositionService(
        broker,
        broker,
        FakeNotifier(),
        InMemoryTradeHistoryRepository(),
        FixedClock(datetime(2026, 1, 2)),
    )
    portfolio = PositionPortfolioService("USD_JPY", service, broker, broker)
    from ogami_oanda.application.services.position_portfolio_service import (
        PortfolioStartupState,
    )

    portfolio.startup_state = PortfolioStartupState.QUARANTINED
    application = LiveApplication(
        "USD_JPY",
        _NoMarket(),
        analysis,
        OrderPlanner(),
        portfolio,
        FixedClock(datetime(2026, 1, 2)),
    )

    result = application.run_once()

    assert result.skipped == ("portfolio_quarantined",)
    assert analysis.calls == 0


@pytest.mark.contract
def test_live_run_once_stops_after_position_sync_quarantines_portfolio():
    class _QuarantineOnSync:
        startup_state = PortfolioStartupState.READY
        pending_mutations = ()

        def __init__(self):
            self.sync_calls = 0
            self.registration_calls = 0

        def sync_all(self, *, current_price=None, dry_run=False):
            del current_price, dry_run
            self.sync_calls += 1
            self.startup_state = PortfolioStartupState.QUARANTINED
            return PortfolioSummary(0, 0, 1, 0)

        def register_plans(self, plans, submit=True):
            del plans, submit
            self.registration_calls += 1
            return RegistrationResult((), ())

    now = datetime(2026, 1, 2, 10, 5, 6)
    clock = FixedClock(now)
    analysis = _NoAnalysis()
    portfolio = _QuarantineOnSync()
    application = LiveApplication(
        "USD_JPY",
        FakeMarketData({}, {"USD_JPY": 150.0}),
        analysis,
        OrderPlanner(),
        portfolio,
        clock,
    )
    application._last_analysis_at = datetime(2026, 1, 2, 10, 0, 0)

    result = application.run_once(now=now)

    assert result.skipped == ("portfolio_quarantined",)
    assert result.summary is not None
    assert result.summary.open == 1
    assert analysis.calls == 0
    assert portfolio.sync_calls == 1
    assert portfolio.registration_calls == 0


@pytest.mark.contract
def test_live_run_once_reconciles_unknown_mutation_before_market_or_analysis():
    class _ReconcilingPortfolio:
        startup_state = PortfolioStartupState.READY

        def __init__(self):
            self.calls = 0

        def reconcile_pending_mutations(self):
            self.calls += 1
            return False

    class _NoMarket:
        def current_quote(self, pair):
            raise AssertionError("unresolved mutation must block market data")

    portfolio = _ReconcilingPortfolio()
    analysis = _NoAnalysis()
    application = LiveApplication(
        "USD_JPY",
        _NoMarket(),
        analysis,
        OrderPlanner(),
        portfolio,
        FixedClock(datetime(2026, 1, 2, 10, 0, 0)),
    )

    result = application.run_once()

    assert result.skipped == ("broker_reconciliation",)
    assert portfolio.calls == 1
    assert analysis.calls == 0
