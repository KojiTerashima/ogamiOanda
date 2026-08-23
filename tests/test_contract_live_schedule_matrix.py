import json
from datetime import datetime
from pathlib import Path

import pytest

from ogami_oanda.application.ports.market_data import MarketQuote
from ogami_oanda.application.ports.position_state import (
    CheckpointLoadResult,
    CheckpointLoadStatus,
    PositionStateCheckpoint,
    account_identity_hash,
)
from ogami_oanda.application.services.market_analysis_service import (
    MarketAnalysisResult,
)
from ogami_oanda.application.services.order_planner import OrderPlanner
from ogami_oanda.application.services.position_portfolio_service import (
    PositionStatePersistenceError,
)
from ogami_oanda.domain.market.currency_pair import currency_pair
from ogami_oanda.domain.orders.models import (
    Direction,
    OrderContext,
    OrderIntent,
    OrderType,
)
from ogami_oanda.domain.positions.managed_position import ManagedPosition
from ogami_oanda.entrypoints.live import LiveApplication, build_live_application
from ogami_oanda.infrastructure.config.models import (
    AppSettings,
    RuntimeAccountConfig,
)
from tests.fakes import (
    FakeBroker,
    FakeMarketData,
    FakeNotifier,
    FixedClock,
    InMemoryTradeHistoryRepository,
)


class _TraceMarket:
    def __init__(self, trace, quote):
        self.trace = trace
        self.quote = quote

    def current_quote(self, pair):
        self.trace.append("quote")
        assert pair == self.quote.pair
        return self.quote


class _TraceAnalysis:
    def __init__(self, trace):
        self.trace = trace

    def analyze(self, pair, decision_time, *, current_price=None):
        self.trace.append("analysis")
        return MarketAnalysisResult((), {}, {})


class _TracePortfolio:
    def __init__(self, trace):
        self.trace = trace

    def sync_all(self, *, current_price=None, dry_run=False):
        self.trace.append("sync")
        return None

    def register_plans(self, plans, submit=True):
        self.trace.append("register")
        return type("_Registration", (), {"accepted": (), "rejected": ()})()


@pytest.mark.contract
@pytest.mark.parametrize("pair_name", ["USD_JPY", "EUR_USD", "AUD_USD"])
def test_live_scheduler_allows_pair_spread_limit_and_blocks_above_it(pair_name):
    pair = currency_pair(pair_name)
    threshold = pair.pips_to_price(pair.spread_limit_pips)
    mid = 150.0 if pair_name == "USD_JPY" else 1.0
    now = datetime(2026, 1, 2, 10, 5, 6)

    allowed_trace = []
    allowed = LiveApplication(
        pair_name,
        _TraceMarket(
            allowed_trace,
            MarketQuote(
                pair_name,
                pair.round_price(mid),
                pair.round_price(mid + threshold),
                pair.round_price(mid + threshold / 2),
            ),
        ),
        _TraceAnalysis(allowed_trace),
        OrderPlanner(),
        _TracePortfolio(allowed_trace),
        FixedClock(now),
    )

    allowed.run_once(
        now=datetime(2026, 1, 2, 10, 0, 5),
        dry_run=True,
    )
    allowed_trace.clear()
    allowed_result = allowed.run_once(dry_run=True)

    assert allowed_result.analysis is not None
    assert allowed_result.skipped == ()
    assert allowed_trace == ["quote", "sync", "analysis", "register", "sync"]

    blocked_trace = []
    blocked = LiveApplication(
        pair_name,
        _TraceMarket(
            blocked_trace,
            MarketQuote(
                pair_name,
                pair.round_price(mid),
                pair.round_price(mid + threshold + pair.pip_value),
                pair.round_price(mid + (threshold + pair.pip_value) / 2),
            ),
        ),
        _TraceAnalysis(blocked_trace),
        OrderPlanner(),
        _TracePortfolio(blocked_trace),
        FixedClock(now),
    )

    blocked.run_once(
        now=datetime(2026, 1, 2, 10, 0, 5),
        dry_run=True,
    )
    blocked_trace.clear()
    blocked_result = blocked.run_once(dry_run=True)

    assert blocked_result.analysis is None
    assert blocked_result.skipped == ("update_only",)
    assert blocked_trace == ["quote", "sync"]


@pytest.mark.contract
@pytest.mark.parametrize(
    ("pair_name", "snapshot_name"),
    [
        ("USD_JPY", "analysis_oracle_usd_jpy.json"),
        ("EUR_USD", "analysis_oracle_eur_usd.json"),
        ("AUD_USD", "analysis_oracle_aud_usd.json"),
    ],
)
def test_fixture_composition_runs_finite_dry_run_without_broker_mutation(
    pair_name,
    snapshot_name,
    analysis_frame_store,
):
    expected = json.loads(
        (Path(__file__).parent / "fixtures" / snapshot_name).read_text(encoding="utf-8")
    )
    frames = analysis_frame_store[pair_name]
    market = FakeMarketData(
        {
            (pair_name, granularity): frames[granularity]
            for granularity in ("M5", "H1", "M30", "S5")
        },
        {pair_name: expected["current_price"]},
    )
    broker = FakeBroker()
    now = datetime.strptime(expected["decision_time"], "%Y/%m/%d %H:%M:%S")
    application = build_live_application(
        AppSettings({"primary": RuntimeAccountConfig("id", "token", "practice")}),
        pair=pair_name,
        market_data=market,
        broker_execution=broker,
        broker_query=broker,
        notifier=FakeNotifier(),
        history=InMemoryTradeHistoryRepository(),
        clock=FixedClock(now),
        cancel_pending_on_start=True,
        dry_run=True,
    )

    initial = application.run_once(
        now=now,
        decision_time=expected["decision_time"],
        dry_run=True,
    )
    following_ticks = application.run_forever(
        dry_run=True,
        sleeper=lambda seconds: (_ for _ in ()).throw(
            AssertionError("a one-tick finite loop must not sleep")
        ),
        max_ticks=1,
    )

    assert initial.analysis is not None
    assert len(initial.plans) == len(expected["legacy_orders"])
    assert all(plan.intent.pair == pair_name for plan in initial.plans)
    assert len(following_ticks) == 1
    assert broker.requests == []
    assert broker.commands == []


@pytest.mark.contract
def test_dry_run_never_writes_runtime_checkpoint(candle_frame):
    class _Repository:
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

    repository = _Repository()
    broker = FakeBroker()
    application = build_live_application(
        AppSettings({"primary": RuntimeAccountConfig("id", "token", "practice")}),
        market_data=FakeMarketData(
            {
                ("USD_JPY", granularity): candle_frame
                for granularity in ("M5", "H1", "M30", "S5")
            },
            {"USD_JPY": 150.0},
        ),
        broker_execution=broker,
        broker_query=broker,
        notifier=FakeNotifier(),
        history=InMemoryTradeHistoryRepository(),
        state_repository=repository,
        clock=FixedClock(datetime(2026, 1, 2, 10, 0, 0)),
        dry_run=True,
    )

    application.run_once(dry_run=True)

    assert repository.saved == []
    assert broker.requests == []
    assert broker.commands == []


@pytest.mark.contract
def test_live_dry_run_never_submits_prepared_checkpoint():
    plan = OrderPlanner().plan(
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
            1,
            "dry-run-prepared",
            1,
            30,
        ),
        OrderContext(150.0, "2026/01/02 10:00:00"),
    )
    prepared = ManagedPosition.registered(
        plan.intent.name,
        "USD_JPY",
    ).with_order_plan(plan, datetime(2026, 1, 2, 10, 0, 0))

    class _Repository:
        def load(self, **_kwargs):
            return CheckpointLoadResult(
                CheckpointLoadStatus.LOADED,
                PositionStateCheckpoint(
                    account_hash=account_identity_hash("id"),
                    pair="USD_JPY",
                    slots=(prepared,) + (None,) * 14,
                    transaction_cursor="100",
                ),
            )

        def save(self, _checkpoint):
            raise AssertionError("dry-run must not persist runtime state")

    broker = FakeBroker()
    application = build_live_application(
        AppSettings(
            {"primary": RuntimeAccountConfig("id", "token", "live")}
        ),
        market_data=FakeMarketData({}, {"USD_JPY": 150.0}),
        broker_execution=broker,
        broker_query=broker,
        notifier=FakeNotifier(),
        history=InMemoryTradeHistoryRepository(),
        state_repository=_Repository(),
        clock=FixedClock(datetime(2026, 1, 2, 10, 0, 0)),
        dry_run=True,
    )

    result = application.run_once(dry_run=True)

    assert result.skipped == ("portfolio_quarantined",)
    assert broker.requests == []
    assert broker.commands == []


@pytest.mark.contract
def test_dry_run_composition_cannot_be_switched_to_broker_mutation(candle_frame):
    class _Repository:
        def load(self, **_kwargs):
            return CheckpointLoadResult(CheckpointLoadStatus.MISSING)

        def save(self, _checkpoint):
            raise AssertionError("read-only composition must not persist")

    broker = FakeBroker()
    application = build_live_application(
        AppSettings(
            {"primary": RuntimeAccountConfig("id", "token", "practice")}
        ),
        market_data=FakeMarketData(
            {
                ("USD_JPY", granularity): candle_frame
                for granularity in ("M5", "H1", "M30", "S5")
            },
            {"USD_JPY": 150.0},
        ),
        broker_execution=broker,
        broker_query=broker,
        notifier=FakeNotifier(),
        history=InMemoryTradeHistoryRepository(),
        state_repository=_Repository(),
        clock=FixedClock(datetime(2026, 1, 2, 10, 0, 0)),
        dry_run=True,
    )
    plan = OrderPlanner().plan(
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
            1,
            "read-only-mutation",
            1,
            30,
        ),
        OrderContext(150.0, "2026/01/02 10:00:00"),
    )

    with pytest.raises(PositionStatePersistenceError, match="read-only"):
        application.portfolio.register_plans([plan], submit=True)

    assert broker.requests == []
    assert broker.commands == []
