"""Configured entry limits share defaults without altering prices or credentials."""

import csv
from datetime import datetime, timedelta, timezone
import json

import pytest
import yaml

from ogami_oanda.application.ports.market_data import MarketQuote
from ogami_oanda.application.services.market_analysis_service import MarketAnalysisResult
from ogami_oanda.application.services.order_planner import OrderPlanner
from ogami_oanda.application.services.practice_order_acceptance_service import (
    PracticeAcceptanceError, PracticeOrderAcceptanceService,
)
from ogami_oanda.application.settings import TradingSettings
from ogami_oanda.domain.market.currency_pair import currency_pair
from ogami_oanda.entrypoints import backtest, live
from ogami_oanda.entrypoints.backtest_run import run_backtest
from ogami_oanda.infrastructure.config import loader
from ogami_oanda.infrastructure.config.models import AppSettings, RuntimeAccountConfig
from ogami_oanda.strategy.shared.contracts import StrategyDecision, StrategyCommand, StrategyCommandAction
from tests.fakes import FakeBroker, FakeNotifier, FixedClock, InMemoryTradeHistoryRepository
from tests.test_backtest_run import START, ExampleStrategy, candles
from tests.test_contract_live_schedule_matrix import _TraceMarket, _TraceAnalysis
from tests.test_contract_practice_order_acceptance import _AcceptanceBroker, _market
from tests.test_contract_strategy_live_entrypoint import _Portfolio, _Strategy, _StateRepository, _intent

PAIRS = ("USD_JPY", "EUR_USD", "AUD_USD")


def test_partial_settings_keep_defaults_and_are_detached():
    supplied = {"USD_JPY": 2.5}
    first = TradingSettings(spread_limit_pips=supplied)
    second = TradingSettings()
    supplied["USD_JPY"] = 9
    assert [first.spread_limit_for(p) for p in PAIRS] == [2.5, 1.5, 1.8]
    assert [second.spread_limit_for(p) for p in PAIRS] == [1.1, 1.5, 1.8]
    assert currency_pair("USD_JPY").spread_limit_pips == 1.1
    with pytest.raises(TypeError):
        first.spread_limit_pips["USD_JPY"] = 9


@pytest.mark.parametrize("overrides", [{}, {"USD_JPY": 0}, {"USD_JPY": 2, "EUR_USD": 3.2, "AUD_USD": 4}])
def test_full_and_spread_only_loaders_agree(tmp_path, overrides):
    path = tmp_path / "settings.yaml"
    path.write_text(yaml.safe_dump({"accounts": {"test": {"account_id": "id", "access_token": "token"}},
                                    "trading": {"spread_limit_pips": overrides}}))
    full = loader.load_settings(path, {})
    assert dict(full.trading.spread_limit_pips) == loader.load_spread_limits(path) == overrides
    for pair in PAIRS:
        assert full.trading.spread_limit_for(pair) == overrides.get(pair, currency_pair(pair).spread_limit_pips)


@pytest.mark.parametrize("text", ["", "{}", "trading: {}", "trading:\n  risk_yen: 12"])
def test_missing_section_keeps_defaults(tmp_path, text):
    path = tmp_path / "settings.yaml"
    path.write_text(text)
    assert loader.load_spread_limits(path) == {}


@pytest.mark.parametrize("value", [-1, True, False, "2.0", None, float("nan"), float("inf"), float("-inf")])
def test_invalid_values_fail_in_both_loaders_and_python_settings(tmp_path, value):
    with pytest.raises(ValueError, match="spread_limit_pips"):
        TradingSettings(spread_limit_pips={"USD_JPY": value})
    path = tmp_path / "settings.yaml"
    path.write_text(yaml.safe_dump({"trading": {"spread_limit_pips": {"USD_JPY": value}}}))
    for load in (loader.load_settings, loader.load_spread_limits):
        with pytest.raises(ValueError, match="spread_limit_pips"):
            load(path)


@pytest.mark.parametrize("document", [[], False, "bad", {"trading": None}, {"trading": []}] + [
    {"trading": {"spread_limit_pips": value}} for value in (None, 2, [], "2", {"GBP_USD": 1})
])
def test_invalid_structures_fail_before_account_validation(tmp_path, document):
    path = tmp_path / "settings.yaml"
    path.write_text(yaml.safe_dump(document))
    for load in (loader.load_settings, loader.load_spread_limits):
        with pytest.raises(ValueError, match="mapping|unsupported pair"):
            load(path)


class Portfolio(_Portfolio):
    def sync_all(self, *, candle_stop_loss=None, **kwargs):
        return super().sync_all(**kwargs)


@pytest.mark.parametrize("pair", PAIRS)
@pytest.mark.parametrize("profile", ["legacy", "original", "plugin"])
@pytest.mark.parametrize("limit,spread,allowed", [(2, 1.6, True), (2, 2, True), (2, 2.1, False),
                                                 (None, 2, False), (0, 0, True), (0, .1, False)])
def test_entry_boundaries_and_original_initial_exception(pair, profile, limit, spread, allowed):
    model = currency_pair(pair)
    mid = 150 if pair == "USD_JPY" else 1
    now = datetime(2026, 1, 2, 3, 5, 6, tzinfo=timezone.utc)
    quote = MarketQuote(pair, mid, mid + model.pips_to_price(spread), mid, source_time=now)
    trace = []
    market = _TraceMarket(trace, quote)
    portfolio = Portfolio(trace)
    if profile == "legacy":
        app = live.LiveApplication(pair, market, _TraceAnalysis(trace), OrderPlanner(), portfolio,
                                   FixedClock(now), spread_limit_pips=limit)
    else:
        strategy = _Strategy(StrategyDecision(), trace)
        strategy.data_requirements = {}
        if profile == "original":
            strategy.evaluation_profile = "original"
            strategy.last_analysis = MarketAnalysisResult((), {}, {})
        app = live.StrategyLiveApplication(pair, strategy, "fixture", market, OrderPlanner(), portfolio,
                                           FixedClock(now), spread_limit_pips=limit)
    first = app.run_once(now=now - timedelta(minutes=5))
    if profile != "plugin":
        assert first.analysis is not None  # The original first-tick exception remains.
    trace.clear()
    result = app.run_once(now=now)
    if profile == "plugin":
        assert ("wide_spread" not in result.skipped) is allowed
        assert "decide" in trace
    else:
        assert (result.analysis is not None) is allowed
        assert ("update_only" not in result.skipped) is allowed
    assert "sync" in trace  # Position management must continue above the limit.


@pytest.mark.parametrize("limit,allowed", [(1.1, False), (2, True)])
def test_plugin_commands_continue_while_only_entries_are_spread_gated(limit, allowed):
    now = START
    command = StrategyCommand(StrategyCommandAction.CANCEL_PENDING, "fixture", "risk")
    strategy = _Strategy(StrategyDecision(intents=(_intent(),), commands=(command,)))
    strategy.data_requirements = {}
    portfolio = Portfolio()
    app = live.StrategyLiveApplication("USD_JPY", strategy, "fixture",
        _TraceMarket([], MarketQuote("USD_JPY", 150, 150.016, 150.008, source_time=now)), OrderPlanner(),
        portfolio, FixedClock(now), spread_limit_pips=limit)
    result = app.run_once()
    assert portfolio.command_calls == [((command,), False)]
    assert bool(portfolio.registration_calls) is allowed
    assert bool(result.plans) is allowed


@pytest.mark.parametrize("plugin", [False, True])
def test_live_builders_receive_configured_pair_limit(plugin):
    settings = AppSettings({"primary": RuntimeAccountConfig("id", "token", "practice")},
                           trading=TradingSettings(spread_limit_pips={"USD_JPY": 2.5}))
    broker = FakeBroker(account_id="id")
    kwargs = dict(market_data=_TraceMarket([], MarketQuote("USD_JPY", 150, 150.016, 150.008)),
                  broker_execution=broker, broker_query=broker, notifier=FakeNotifier(),
                  history=InMemoryTradeHistoryRepository(), state_repository=_StateRepository(),
                  clock=FixedClock(START), dry_run=True)
    if plugin:
        app = live.build_strategy_live_application(settings, _Strategy(StrategyDecision()), "fixture", **kwargs)
    else:
        app = live.build_live_application(settings, candidate_builder=lambda *_: [], **kwargs)
    assert app.spread_limit_pips == 2.5


@pytest.mark.parametrize("route", ["matrix", "strategy", "intents"])
@pytest.mark.parametrize("limit,allowed", [(.5, False), (1, True), (2, True)])
def test_practice_fake_order_paths_share_configured_limit(route, limit, allowed):
    from ogami_oanda.domain.orders.models import OrderContext

    broker = _AcceptanceBroker()
    market = _market()
    market.candles = lambda *_: None
    service = PracticeOrderAcceptanceService(market, broker, broker,
        trading_settings=TradingSettings(spread_limit_pips={"USD_JPY": limit}),
        clock=lambda: START)
    def run():
        if route == "matrix":
            return service.run(("USD_JPY",))
        if route == "strategy":
            return service.run_strategy(_Strategy(StrategyDecision(intents=(_intent(),))), pair="USD_JPY")
        return service.run_strategy_intents((_intent(),), contexts={"USD_JPY": OrderContext(150, START.isoformat())}, pair="USD_JPY")
    if allowed:
        assert run().success
        assert broker.requests
    else:
        with pytest.raises(PracticeAcceptanceError, match="spread"):
            run()
        assert not broker.requests


class EntryStrategy(ExampleStrategy):
    def decide(self, value):
        if self.count == 0:
            return super().decide(value)
        self.count += 1
        return StrategyDecision()


@pytest.mark.parametrize("value", [-1, True, "2", float("nan"), float("inf")])
def test_invalid_api_override_is_rejected_before_outputs(tmp_path, value):
    with pytest.raises(ValueError, match="spread_limit_pips"):
        run_backtest(EntryStrategy(), "fixture", "USD_JPY", candles(), START,
                     START + timedelta(minutes=1), initial_balance=10000, output_dir=tmp_path / "run",
                     spread_limit_pips=value)
    assert not (tmp_path / "run").exists()


@pytest.mark.parametrize("failure", [False, True])
@pytest.mark.parametrize("limit", [None, 2.5])
def test_api_records_effective_limit_at_start_and_finish_despite_forged_metadata(tmp_path, failure, limit):
    output = tmp_path / "run"
    expected = 1.1 if limit is None else limit
    def values():
        initial = json.loads((output / "run.json").read_text())
        assert initial["status"] == "running"
        assert initial["spread_limit_pips"] == expected
        for index, candle in enumerate(candles()):
            if failure and index == 27:
                raise RuntimeError("fixture interruption")
            yield candle
    def run():
        return run_backtest(EntryStrategy(), "fixture", "USD_JPY", values(), START,
            START + timedelta(minutes=1), initial_balance=10000, output_dir=output,
            spread_limit_pips=limit, metadata={"spread_limit_pips": 999})
    if failure:
        with pytest.raises(RuntimeError, match="fixture interruption"):
            run()
    else:
        run()
    final = json.loads((output / "run.json").read_text())
    assert final["spread_limit_pips"] == expected
    assert final["status"] == ("failed" if failure else "complete")


@pytest.mark.parametrize("limit", [1.1, 2.0])
def test_cli_config_is_offline_and_agrees_with_api_and_repeats(tmp_path, monkeypatch, limit):
    from ogami_oanda.adapters.repositories.historical_store import read_mid_csv

    source = tmp_path / "mid.csv"
    with source.open("w", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["time", "open", "high", "low", "close"])
        for candle in candles():
            writer.writerow([candle.time.isoformat(), *([candle.mid.close] * 4)])
    config = tmp_path / "settings.yaml"
    # Deliberately invalid/unresolved unrelated sections must never be consumed.
    config.write_text(yaml.safe_dump({"accounts": "${MISSING_CREDENTIAL}", "notifications": "unused",
        "trading": {"default_pair": "AUD_USD", "risk_yen": "unused", "max_positions": "unused",
                    "spread_limit_pips": {"USD_JPY": limit}}}))
    def forbidden(*args, **kwargs):
        raise AssertionError("offline replay must not resolve credentials or build live services")
    monkeypatch.setattr(loader, "load_settings", forbidden)
    monkeypatch.setattr(loader, "_environment_value", forbidden)
    monkeypatch.setattr(live, "build_live_application", forbidden)
    monkeypatch.setattr(live, "build_strategy_live_application", forbidden)
    monkeypatch.setattr(backtest, "select_strategy", lambda _: (EntryStrategy(), "fixture", {}))
    for name in ("cli", "repeat"):
        assert backtest.main(["run", "--strategy", "matcha", "--pair", "USD_JPY", "--from", START.isoformat(),
            "--to", (START + timedelta(minutes=1)).isoformat(), "--mid-csv", str(source),
            "--fixed-spread-pips", "1.6", "--initial-balance", "10000", "--output-dir", str(tmp_path / name),
            "--config", str(config)]) == 0
    result = run_backtest(EntryStrategy(), "fixture", "USD_JPY", read_mid_csv(source, "USD_JPY", 1.6),
        START, START + timedelta(minutes=1), initial_balance=10000, output_dir=tmp_path / "api", spread_limit_pips=limit)
    assert result["trade_count"] == (1 if limit == 2 else 0)
    for file in ("orders.csv", "trades.csv", "equity.csv", "summary.json", "gaps.csv"):
        assert (tmp_path / "cli" / file).read_bytes() == (tmp_path / "api" / file).read_bytes()
        assert (tmp_path / "cli" / file).read_bytes() == (tmp_path / "repeat" / file).read_bytes()
    for name in ("cli", "api"):
        record = json.loads((tmp_path / name / "run.json").read_text())
        assert record["spread_limit_pips"] == limit
        assert "MISSING_CREDENTIAL" not in json.dumps(record)
        assert record["pair"] == "USD_JPY"
    assert (tmp_path / "cli" / "run.json").read_bytes() == (tmp_path / "repeat" / "run.json").read_bytes()


def test_different_effective_limits_cannot_pass_repeat_comparison(tmp_path):
    from tests.test_backtest_acceptance_verification import AUDIT
    strategy = _Strategy(StrategyDecision())
    strategy.data_requirements = {}
    for limit in (1, 2):
        run_backtest(strategy, "fixture", "USD_JPY", candles(), START, START + timedelta(minutes=1),
                     initial_balance=10000, output_dir=tmp_path / str(limit), spread_limit_pips=limit)
    with pytest.raises(ValueError, match="provenance"):
        AUDIT["compare_results"](tmp_path / "1", tmp_path / "2")


def test_malformed_config_does_not_render_private_yaml(tmp_path):
    path = tmp_path / "settings.yaml"
    path.write_text("accounts: [sentinel-private-value\n")
    with pytest.raises(ValueError) as error:
        loader.load_spread_limits(path)
    assert "sentinel" not in str(error.value)
