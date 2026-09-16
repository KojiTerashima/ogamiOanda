"""Exercise composed notification delivery with in-memory broker and HTTP ports."""

from dataclasses import replace
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from ogami_oanda.application.ports.broker import OrderSubmissionResult
from ogami_oanda.application.ports.position_state import CheckpointLoadResult, CheckpointLoadStatus
from ogami_oanda.application.services.order_planner import OrderPlanner
from ogami_oanda.application.services.position_portfolio_service import PortfolioStartupState
from ogami_oanda.domain.orders.models import Direction, OrderContext, OrderIntent, OrderType
from ogami_oanda.domain.positions.managed_position import ManagedPosition
from ogami_oanda.domain.positions.models import OrderState, PositionSnapshot, TradeState
from ogami_oanda.entrypoints import live
from ogami_oanda.infrastructure.config.models import AppSettings, NotificationSettings, RuntimeAccountConfig
from tests.fakes import FakeBroker, FakeMarketData, FixedClock, InMemoryTradeHistoryRepository

ROUTES = [("original", "USD_JPY"), ("original", "EUR_USD"), ("original", "AUD_USD"), ("matcha", "USD_JPY")]
NOW = datetime(2026, 1, 2, 3, 4, 5)


class _Http:
    def __init__(self):
        self.calls = []

    def post(self, url, json):
        self.calls.append((url, json))


class _StateRepository:
    def __init__(self, status):
        self.status = status
        self.saved = []

    def load(self, **kwargs):
        return CheckpointLoadResult(self.status)

    def save(self, checkpoint):
        self.saved.append(checkpoint)


def _build_runtime(monkeypatch, strategy, pair, *, status=CheckpointLoadStatus.MISSING, analysis=None):
    http = _Http()
    broker = FakeBroker()
    history = InMemoryTradeHistoryRepository()
    repository = _StateRepository(status)
    settings = AppSettings(
        {"primary": RuntimeAccountConfig("id", "token", "practice")},
        notifications=NotificationSettings(
            pair_webhooks={pair: "legacy-route"},
            strategy_pair_webhooks={name: {pair: f"{name}-{pair}"} for name in ("original", "matcha")},
        ),
    )
    monkeypatch.setattr(live, "create_http_session", lambda: http)
    dependencies = dict(
        pair=pair, market_data=FakeMarketData({}, {}), broker_execution=broker,
        broker_query=broker, history=history, state_repository=repository, clock=FixedClock(NOW),
    )
    if strategy == "original":
        if analysis is None:
            dependencies["candidate_builder"] = lambda *args, **kwargs: []
        else:
            monkeypatch.setattr(live, "MainSourceAnalysis", lambda **kwargs: SimpleNamespace(analysis_name=kwargs["analysis_name"]))
            dependencies["analysis_name"] = analysis
        application = live.build_live_application(settings, **dependencies)
    else:
        application = live.build_strategy_live_application(
            settings, object(), "unchanged-checkpoint-id",
            **({"notification_strategy_name": strategy} if strategy is not None else {}),
            **dependencies,
        )
    return application, broker, http, history


def _plan(pair):
    price = 150.0 if pair == "USD_JPY" else 1.1
    return OrderPlanner().plan(
        OrderIntent(pair, Direction.BUY, OrderType.LIMIT, price, True, 10, False, 10, False, 1000, "notice-test", 1, 30),
        OrderContext(price, "2026/01/02 03:04:05"),
    )


@pytest.mark.contract
@pytest.mark.parametrize(("strategy", "pair"), ROUTES)
@pytest.mark.parametrize(("result", "message"), [
    (OrderSubmissionResult.pending("order-1"), "Order submitted:"),
    (OrderSubmissionResult.filled(order_id="order-1", trade_id="trade-1"), "Order filled:"),
    (OrderSubmissionResult.rejected("rejected"), "Order rejected:"),
    (OrderSubmissionResult.unknown("unconfirmed"), "Order submission uncertain:"),
])
def test_order_outcome_notifications_use_the_composed_strategy(monkeypatch, strategy, pair, result, message):
    app, broker, http, _ = _build_runtime(monkeypatch, strategy, pair)
    monkeypatch.setattr(broker, "submit", lambda request: result)
    service = app.portfolio.position_service
    service.register(ManagedPosition.registered("notice-test", pair), _plan(pair))
    assert len(http.calls) == 1
    assert http.calls[0][0] == f"{strategy}-{pair}"
    assert message in http.calls[0][1]["content"]
    if strategy == "matcha":
        assert app.strategy_id == app.portfolio.strategy_id == "unchanged-checkpoint-id"


@pytest.mark.contract
@pytest.mark.parametrize(("strategy", "pair"), ROUTES)
def test_trade_closure_and_runtime_quarantine_use_the_same_route(monkeypatch, strategy, pair):
    app, broker, http, history = _build_runtime(monkeypatch, strategy, pair)
    portfolio = app.portfolio
    portfolio.register_plans([_plan(pair)], submit=True)
    broker.orders["order-1"] = PositionSnapshot(
        "notice-test", pair, OrderState.FILLED, TradeState.OPEN,
        order_id="order-1", trade_id="trade-1", life=True, direction=1,
        units=1000, target_price=_plan(pair).target_price,
    )
    portfolio.sync_all()
    broker.trades["trade-1"] = replace(
        broker.orders["order-1"], trade_state=TradeState.CLOSED,
        life=False, realized_pl=10, average_close_price=_plan(pair).target_price,
    )
    portfolio.sync_all()
    portfolio.sync_all()
    assert len(history.records) == 1
    assert [url for url, _ in http.calls] == [f"{strategy}-{pair}"] * 2
    assert "Trade closed:" in http.calls[-1][1]["content"]

    # The next pending order has no broker snapshot or terminal evidence.
    portfolio.register_plans([_plan(pair)], submit=True)
    portfolio.sync_all()
    portfolio.sync_all()
    assert portfolio.startup_state is PortfolioStartupState.QUARANTINED
    assert http.calls[-1][0] == f"{strategy}-{pair}"
    assert "Portfolio quarantined:" in http.calls[-1][1]["content"]
    assert sum("Portfolio quarantined:" in payload["content"] for _, payload in http.calls) == 1


@pytest.mark.contract
@pytest.mark.parametrize(("strategy", "pair"), ROUTES)
def test_startup_quarantine_uses_the_composed_strategy(monkeypatch, strategy, pair):
    app, broker, http, _ = _build_runtime(monkeypatch, strategy, pair, status=CheckpointLoadStatus.QUARANTINED)
    assert app.portfolio.startup_state is PortfolioStartupState.QUARANTINED
    assert broker.requests == []
    assert len(http.calls) == 1
    assert http.calls[0][0] == f"{strategy}-{pair}"
    assert "Portfolio startup quarantined:" in http.calls[0][1]["content"]


@pytest.mark.contract
@pytest.mark.parametrize("analysis", ["line", "resistance_breakout"])
def test_original_analysis_choice_does_not_change_notification_route(monkeypatch, analysis):
    app, _, http, _ = _build_runtime(monkeypatch, "original", "USD_JPY", analysis=analysis)
    app.portfolio.register_plans([_plan("USD_JPY")], submit=True)
    assert [url for url, _ in http.calls] == ["original-USD_JPY"]
    expected_id = "builtin-line" if analysis == "line" else "builtin-line:analysis=resistance_breakout"
    assert app.portfolio.strategy_id == expected_id


@pytest.mark.contract
def test_python_builder_without_notification_name_does_not_use_pair_webhook(monkeypatch):
    app, _, http, _ = _build_runtime(monkeypatch, None, "USD_JPY")
    app.portfolio.register_plans([_plan("USD_JPY")], submit=True)
    assert http.calls == []
    assert app.strategy_id == "unchanged-checkpoint-id"


@pytest.mark.contract
@pytest.mark.parametrize(("strategy", "pair"), ROUTES)
def test_dry_run_registration_does_not_add_notifications(monkeypatch, strategy, pair):
    app, broker, http, history = _build_runtime(monkeypatch, strategy, pair)
    app.portfolio.register_plans([_plan(pair)], submit=False)
    assert http.calls == broker.requests == history.records == []


@pytest.mark.contract
@pytest.mark.parametrize(("relative", "expected"), [
    ("original/strategy.py", "original"), ("matcha/strategy.py", "matcha"),
    ("custom/variant/strategy.py", "custom"), ("custom.py", "custom"),
])
def test_plugin_notification_name_uses_owner_directory(relative, expected):
    root = Path(live.__file__).resolve().parents[1] / "strategy"
    assert live._notification_strategy_name(root / relative) == expected


@pytest.mark.contract
def test_plugin_notification_name_uses_resolved_path(tmp_path):
    root = Path(live.__file__).resolve().parents[1] / "strategy"
    alias = tmp_path / "alias.py"
    alias.symlink_to(root / "matcha" / "strategy.py")
    assert live._notification_strategy_name(alias) == "matcha"
