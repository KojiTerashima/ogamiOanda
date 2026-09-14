"""Owned breakout orders use the existing broker, lifecycle and recovery contracts."""

from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json
from types import SimpleNamespace

import pytest

from ogami_oanda.adapters.backtest.broker import SimulatedBroker
from ogami_oanda.adapters.legacy.main_analysis.orders import from_native_order
from ogami_oanda.adapters.oanda.mappers import broker_request_to_oanda
from ogami_oanda.adapters.repositories.json_position_state import JsonPositionStateRepository
from ogami_oanda.application.ports.position_state import PositionStateCheckpoint, account_identity_hash
from ogami_oanda.application.services.order_planner import OrderPlanner
from ogami_oanda.application.services.position_portfolio_service import PortfolioStartupState, PositionPortfolioService
from ogami_oanda.application.services.position_service import CandleStopLossInput, PositionService
from ogami_oanda.domain.analysis.main_contracts import AnalysisIntegrityError
from ogami_oanda.domain.analysis.main_orders import to_order_intents
from ogami_oanda.domain.market.history import HistoricalCandle, OHLC
from ogami_oanda.domain.orders.models import OrderContext
from ogami_oanda.domain.positions.managed_position import ManagedPosition
from ogami_oanda.strategy.shared.position_management.hedge import HedgeCommand
from tests.fakes import FakeBroker, FakeNotifier, FixedClock, InMemoryTradeHistoryRepository

START = datetime(2026, 1, 2, 10, tzinfo=timezone.utc)


def native_order(**metadata):
    return SimpleNamespace(
        order_json={"pair": "USD_JPY", "origin": "resistance_breakout", "owner_tag": "resistance_breakout", **metadata},
        exe_order_plan={}, instrument="USD_JPY", direction=1, ls_type="STOP", target_price=150.1,
        tp_price=150.3, lc_price=150.0, units=1000, name="breakout", priority=5,
        order_timeout_min=60, trade_timeout_min=60, decision_time="2026/01/02 10:00:00", lc_change=[],
    )


def plan_for(order=None, analysis="resistance_breakout"):
    candidate = from_native_order(order or native_order(), analysis)
    intent, = to_order_intents((candidate,))
    return OrderPlanner().plan(intent, OrderContext(150.05, "2026/01/02 10:00:00"))


def service_for(broker, clock, **kwargs):
    positions = PositionService(broker, broker, FakeNotifier(), InMemoryTradeHistoryRepository(), clock)
    portfolio = PositionPortfolioService("USD_JPY", positions, broker, broker, **kwargs)
    return portfolio


@pytest.mark.parametrize("metadata,expected", [
    ({"owner_tag": "new_owner"}, "unsupported"),
    ({"owner_tag": ""}, "unsupported"),
    ({"origin": "changed"}, "unsupported"),
    ({"allow_followup_order": False}, "unsupported"),
    ({"profit_lock_ratio": .5}, "unsupported"),
    ({"line_order_mode": "predict_reversal"}, "unsupported"),
    ({"order_permission": False}, "waiting"),
    ({"execution_mode": "trial"}, "trial"),
    ({"execution_mode": "watch"}, "unsupported"),
])
def test_owned_orders_do_not_bypass_other_management_gates(metadata, expected):
    candidate = from_native_order(native_order(**metadata), "resistance_breakout")
    assert candidate.execution == expected
    assert to_order_intents((candidate,)) == ()


def test_owner_exception_is_limited_to_the_selected_analysis():
    candidate = from_native_order(native_order(), "line")
    assert candidate.execution == "unsupported"
    with pytest.raises(AnalysisIntegrityError, match="positive trade timeout"):
        order = native_order()
        order.trade_timeout_min = 0
        from_native_order(order, "resistance_breakout")


@pytest.mark.parametrize("enabled", [False, True])
def test_oanda_tag_keeps_submission_id_and_respects_extension_setting(enabled):
    request = plan_for().broker_request
    assert request.owner_tag == "resistance_breakout"
    data = broker_request_to_oanda(request, include_client_extensions=enabled)["order"]
    assert float(data["price"]) == 150.1
    if enabled:
        assert data["clientExtensions"] == data["tradeClientExtensions"] == {
            "id": request.client_reference, "tag": "resistance_breakout"}
    else:
        assert "clientExtensions" not in data and "tradeClientExtensions" not in data
    ordinary = replace(request, owner_tag="")
    assert broker_request_to_oanda(ordinary, include_client_extensions=True)["order"]["clientExtensions"]["tag"] == "ogami-oanda"


def test_tags_survive_checkpoint_and_do_not_participate_in_hedge_closing(tmp_path):
    plan = plan_for()
    owned = (ManagedPosition.registered("breakout", "USD_JPY").with_order_plan(plan, START)
             .pending("order-1").filled("trade-1", START + timedelta(minutes=10)))
    repo = JsonPositionStateRepository(tmp_path / "positions.json")
    identity = account_identity_hash("offline-test")
    checkpoint = PositionStateCheckpoint(identity, "USD_JPY", (owned,) + (None,) * 14,
                                         strategy_id="builtin-line:analysis=resistance_breakout")
    repo.save(checkpoint)
    loaded = repo.load(expected_account_hash=identity, expected_pair="USD_JPY").checkpoint
    restored = loaded.slots[0]
    restored_plan = restored.runtime.order_plan
    assert restored_plan.broker_request.owner_tag == "resistance_breakout"
    assert restored_plan.intent.metadata["owner_tag"] == "resistance_breakout"
    assert restored_plan.intent.metadata["main_analysis"] == "resistance_breakout"
    assert restored_plan.intent.metadata["trade_timeout_enabled"] is True
    assert restored.runtime.filled_at == START + timedelta(minutes=10)

    # An injected close decision makes accidental admission observable even if
    # the historical hedge policy returns no commands for this price history.
    class CloseEligible:
        def close_commands(self, positions):
            return tuple(HedgeCommand("close_trade", p.position_id) for p in positions)
    clock = FixedClock(START)
    broker = FakeBroker()
    portfolio = service_for(broker, clock, hedge_policy=CloseEligible())
    ordinary_plan = plan_for(native_order(owner_tag="", origin=""), "line")
    ordinary = (ManagedPosition.registered("ordinary", "USD_JPY").with_order_plan(ordinary_plan, START)
                .filled("trade-2", START))
    commands = portfolio._apply_hedge([restored, ordinary], dry_run=True)
    assert [command.reference_id for command in commands] == ["trade-2"]
    assert broker.commands == []


def test_old_checkpoint_without_owner_field_remains_readable(tmp_path):
    plan = plan_for(native_order(owner_tag="", origin=""), "line")
    position = ManagedPosition.registered("ordinary", "USD_JPY").with_order_plan(plan, START)
    identity = account_identity_hash("offline-test")
    repo = JsonPositionStateRepository(tmp_path / "positions.json")
    repo.save(PositionStateCheckpoint(identity, "USD_JPY", (position,) + (None,) * 14))
    path, = tmp_path.glob("*.json")
    raw = json.loads(path.read_text())
    raw["slots"][0]["runtime"]["order_plan"]["broker_request"].pop("owner_tag")
    path.write_text(json.dumps(raw))
    loaded = repo.load(expected_account_hash=identity, expected_pair="USD_JPY").checkpoint
    assert loaded.slots[0].runtime.order_plan.broker_request.owner_tag == ""


@pytest.mark.parametrize("owned", [False, True])
def test_virtual_order_times_out_from_fill_and_owner_still_allows_candle_sl(owned):
    plan = plan_for() if owned else plan_for(native_order(owner_tag="", origin=""), "line")
    clock = FixedClock(START)
    broker = SimulatedBroker("USD_JPY", clock, initial_balance=10000)
    portfolio = service_for(broker, clock)
    portfolio.startup_state = PortfolioStartupState.READY
    assert portfolio.register_plans([plan]).accepted == ("breakout",)
    assert broker.order("order-1").trade_id is None

    def advance(at):
        clock.value = at
        price = OHLC(150.1, 150.1, 150.1, 150.1)
        broker.advance(HistoricalCandle(at, price, price, price))
        portfolio.sync_all(current_price=150.1)

    filled_at = START + timedelta(minutes=10)
    advance(filled_at)
    position = portfolio.slots[0]
    assert position.runtime.filled_at == filled_at
    assert position.snapshot.trade_id == "trade-1"
    advance(START + timedelta(minutes=60))
    assert not portfolio.slots[0].runtime.close_requested
    advance(filled_at + timedelta(minutes=60))
    assert portfolio.slots[0].runtime.close_requested is owned
    advance(filled_at + timedelta(minutes=60, seconds=5))
    assert (broker.trade("trade-1").trade_state.value == "CLOSED") is owned

    if owned:
        # Ownership does not disable the existing candle-driven SL rule.
        position = position.with_runtime(close_requested=False)
        fake = FakeBroker()
        fake.trades["trade-1"] = position.snapshot
        clock.value = filled_at + timedelta(minutes=5, seconds=10)
        service = service_for(fake, clock).position_service
        result = service.sync_result(position, current_price=150.2, dry_run=True,
                                     candle_stop_loss=CandleStopLossInput({"count": 3, "direction": 1},
                                                                        {"low": 150.15, "high": 150.2}))
        assert [c.action for c in result.commands] == ["amend_stop_loss"]


@pytest.mark.parametrize("old_name,new_name", [("line", "resistance_breakout"), ("resistance_breakout", "line")])
def test_analysis_change_with_active_checkpoint_stops_without_adoption(tmp_path, old_name, new_name):
    from ogami_oanda.entrypoints.main_analysis import analysis_strategy_id
    identity = account_identity_hash("offline-test")
    old_id = analysis_strategy_id("builtin-line", SimpleNamespace(analysis_name=old_name))
    new_id = analysis_strategy_id("builtin-line", SimpleNamespace(analysis_name=new_name))
    plan = plan_for() if old_name != "line" else plan_for(native_order(owner_tag="", origin=""), "line")
    active = ManagedPosition.registered("breakout", "USD_JPY").with_order_plan(plan, START).pending("order-1")
    repo = JsonPositionStateRepository(tmp_path / "positions.json")
    repo.save(PositionStateCheckpoint(identity, "USD_JPY", (active,) + (None,) * 14, strategy_id=old_id))
    original_bytes = repo.path.read_bytes()
    broker = FakeBroker()
    portfolio = service_for(broker, FixedClock(START), state_repository=repo, account_hash=identity, strategy_id=new_id)
    result = portfolio.restore_and_reconcile()
    assert result.state is PortfolioStartupState.QUARANTINED
    assert result.reason == "checkpoint strategy does not match selected strategy"
    assert portfolio.slots == [None] * 15
    assert repo.path.read_bytes() == original_bytes
    assert not broker.commands and not broker.requests


def test_backtest_routes_selected_candidates_to_virtual_trades_and_report(tmp_path):
    from ogami_oanda.domain.analysis.main_contracts import MainAnalysisEvaluation
    from ogami_oanda.entrypoints.backtest_run import run_backtest
    from ogami_oanda.strategy.original.strategy import OriginalStrategy

    candidate = from_native_order(native_order(), "resistance_breakout")
    class Backend:
        analysis_name = "resistance_breakout"
        source_directory = tmp_path / "not-required-for-injected-backend"
        calls = 0

        def evaluate(self, request):
            self.calls += 1
            candidates = (candidate,) if self.calls == 1 else ()
            assert request.mode == "inspection"
            return MainAnalysisEvaluation(to_order_intents(candidates), candidates, request.candle_frames,
                                          {}, {}, OrderContext(request.current_price, str(request.decision_time)),
                                          {"analysis_name": self.analysis_name})

    backend = Backend()
    strategy = OriginalStrategy(analysis_backend=backend)
    def history():
        value = OHLC(150.15, 150.15, 150.15, 150.15)
        # Like the existing replay fixture, use M5 warmup records and S5 execution.
        for index in range(-3600, 0):
            yield HistoricalCandle(START + timedelta(minutes=5 * index), value, value, value)
        for offset in range(0, 60, 5):
            yield HistoricalCandle(START + timedelta(seconds=offset), value, value, value)

    output = tmp_path / "result"
    result = run_backtest(strategy, "test-original", "USD_JPY", history(), START, START + timedelta(minutes=1),
                          initial_balance=10000, output_dir=output, analysis_name="resistance_breakout")
    assert backend.calls >= 1
    assert result["trade_count"] == 1
    report = json.loads((output / "run.json").read_text())
    assert report["analysis_name"] == "resistance_breakout"
    assert report["strategy_id"] == "test-original:analysis=resistance_breakout"
    assert report["status"] == "complete"
