"""Executable analysis selection, including CLI and dependency-injection boundaries."""

from argparse import Namespace
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from ogami_oanda.adapters.legacy.main_analysis import MainSourceAnalysis
from ogami_oanda.adapters.legacy.main_analysis.source import SOURCE_MODULES
from ogami_oanda.domain.analysis.main_contracts import UnsupportedAnalysisDependency
from ogami_oanda.entrypoints import backtest, live
from ogami_oanda.entrypoints.main_analysis import analysis_strategy_id, bind_main_analysis
from ogami_oanda.strategy.original.strategy import OriginalStrategy
from ogami_oanda.strategy.shared.loader import load_strategy
from tests.fakes.main_analysis import request_for


@pytest.fixture
def source_directory(tmp_path):
    directory = tmp_path / "main"
    directory.mkdir()
    for module in SOURCE_MODULES:
        (directory / f"{module}.py").write_text("")
    return directory


def arguments(directory, analysis_name=None, **changes):
    values = dict(command="run", strategy="original", strategy_py=None, strategy_yaml=None,
                  pair="USD_JPY", risk_yen=500, line_units=1, main_analysis_dir=directory,
                  analysis_name=analysis_name)
    return Namespace(**(values | changes))


@pytest.mark.parametrize("name", ["line", "resistance_breakout"])
def test_selection_binds_original_and_packaged_plugin(name, source_directory):
    root = Path(__file__).parents[1] / "src/ogami_oanda/strategy/original"
    plugin = load_strategy(root / "strategy.py", root / "parameters.yaml")
    for strategy in (OriginalStrategy(), plugin.strategy):
        backend = bind_main_analysis(strategy, mode="inspection", main_analysis_dir=source_directory, analysis_name=name)
        assert backend.analysis_name == name
        with pytest.raises(AttributeError):
            backend.analysis_name = "line"
        assert bind_main_analysis(strategy, mode="live", main_analysis_dir="missing", analysis_name=name) is backend
        assert strategy.analysis.analysis_mode == "live"
    selected, identity, metadata = backtest.select_strategy(arguments(source_directory, name))
    assert selected.analysis.analysis_backend.analysis_name == name
    assert metadata["analysis_name"] == name
    assert (":analysis=resistance_breakout" in identity) == (name == "resistance_breakout")
    assert analysis_strategy_id(identity, selected.analysis.analysis_backend) == identity


def test_default_and_explicit_line_keep_same_identity(source_directory):
    omitted = backtest.select_strategy(arguments(source_directory))
    explicit = backtest.select_strategy(arguments(source_directory, "line"))
    assert omitted[1:] == explicit[1:]
    assert analysis_strategy_id("builtin-line", omitted[0].analysis.analysis_backend) == "builtin-line"


@pytest.mark.parametrize("injected", ["line", "custom", "candidate"])
def test_explicit_selection_cannot_replace_an_injected_dependency(injected, source_directory):
    if injected == "candidate":
        strategy = OriginalStrategy(candidate_builder=lambda *args: [])
    else:
        backend = (MainSourceAnalysis(source_directory=source_directory) if injected == "line"
                   else SimpleNamespace(evaluate=lambda request: None))
        strategy = OriginalStrategy(analysis_backend=backend)
    previous = strategy.analysis.analysis_backend
    with pytest.raises(ValueError, match="conflicts"):
        bind_main_analysis(strategy, mode="live", analysis_name="resistance_breakout", main_analysis_dir="missing")
    assert strategy.analysis.analysis_backend is previous
    assert bind_main_analysis(strategy, mode="inspection", main_analysis_dir="missing") is previous


@pytest.mark.parametrize("name", ["flip", "double_top", "", None])
def test_backend_rejects_unsupported_names_before_source_access(name, tmp_path):
    with pytest.raises(ValueError, match="unsupported main analysis"):
        MainSourceAnalysis(analysis_name=name, source_directory=tmp_path / "absent")


@pytest.mark.parametrize("plugin", [False, True])
def test_breakout_missing_source_fails_before_live_account_io(plugin, tmp_path):
    with pytest.raises(UnsupportedAnalysisDependency, match="absent"):
        if plugin:
            live.build_strategy_live_application(object(), OriginalStrategy(), "test",
                                                 analysis_name="resistance_breakout", main_analysis_dir=tmp_path / "absent")
        else:
            live.build_live_application(object(), analysis_name="resistance_breakout", main_analysis_dir=tmp_path / "absent")
    if not plugin:
        with pytest.raises(ValueError, match="conflicts"):
            live.build_live_application(object(), candidate_builder=lambda *args: [], analysis_name="line")


@pytest.mark.parametrize("extra", [
    ["--strategy", "matcha"],
    ["--offline-smoke", "--dry-run", "--once"],
])
def test_live_rejects_incompatible_selection_before_io(extra, monkeypatch):
    def unexpected(*args, **kwargs):
        raise AssertionError("invalid selection must not read settings or start a client")
    monkeypatch.setattr(live, "load_settings", unexpected)
    monkeypatch.setattr(live, "OandaClient", unexpected)
    with pytest.raises(SystemExit) as error:
        live.main(["--analysis", "resistance_breakout", *extra])
    assert error.value.code == 2


@pytest.mark.parametrize("plugin", [False, True])
@pytest.mark.parametrize("name", ["line", "resistance_breakout"])
def test_live_cli_passes_analysis_to_both_compositions(plugin, name, monkeypatch, capsys):
    calls = []
    from ogami_oanda.application.services.position_portfolio_service import RegistrationResult
    backend = SimpleNamespace(analysis_name=name)
    if name == "resistance_breakout":
        backend.source_directory = "native main"
    app = SimpleNamespace(analysis=SimpleNamespace(analysis_backend=backend),
                          run_resilient_once=lambda **kwargs: live.LiveRunResult(None, RegistrationResult((), ())))
    monkeypatch.setattr(live, "load_settings", lambda path: object())
    monkeypatch.setattr(live, "load_strategy", lambda *args: SimpleNamespace(strategy=OriginalStrategy(), strategy_id="test",
        python_path=Path(live.__file__).resolve().parents[1] / "strategy" / "original" / "strategy.py"))
    def build(*args, **kwargs):
        calls.append(kwargs)
        return app
    monkeypatch.setattr(live, "build_live_application", build)
    monkeypatch.setattr(live, "build_strategy_live_application", build)
    selection = ["--strategy-py", "original.py", "--strategy-yaml", "original.yaml"] if plugin else ["--strategy", "original"]
    assert live.main(["--config", "unused", "--analysis", name, "--dry-run", "--once", *selection]) == 0
    assert calls[0]["analysis_name"] == name
    if plugin:
        assert calls[0]["notification_strategy_name"] == "original"
    assert f"[ANALYSIS] name={name}" in capsys.readouterr().out


def test_backtest_rejects_matcha_selection_and_fetch_has_no_option(tmp_path):
    with pytest.raises(ValueError, match="--analysis requires"):
        backtest.select_strategy(arguments(tmp_path / "absent", "line", strategy="matcha"))
    with pytest.raises(SystemExit):
        backtest.parser().parse_args(["fetch", "--analysis", "line", "--strategy", "original", "--pair", "USD_JPY",
                                      "--from", "2024-01-01T00:00:00Z", "--to", "2024-01-02T00:00:00Z",
                                      "--data-dir", "unused", "--config", "unused"])


@pytest.mark.parametrize("pair", ["USD_JPY", "EUR_USD", "AUD_USD"])
def test_selected_breakout_matches_native_resolved_prices_and_risk(pair, main_source_directory):
    backend = MainSourceAnalysis(source_directory=main_source_directory, analysis_name="resistance_breakout")
    request = replace(request_for(pair), risk_yen=25)
    evaluation = backend.evaluate(request)
    assert evaluation.candidates and len(evaluation.intents) == len(evaluation.candidates)
    with backend.evaluation(request) as session:
        source = session.runtime.load("fResistanceBreakoutAnalysis")
        policy = replace(source.LIVE_TRIAL_POLICY_V1, risk_yen=25)
        orders = source.build_orders_for_decision(session.candles, mode=request.mode, policy=policy)
        assert len(orders) == len(evaluation.candidates)
        for native, candidate, intent in zip(orders, evaluation.candidates, evaluation.intents):
            # Compare native values directly; do not reuse the adapter's conversion as an oracle.
            assert (candidate.target_price, candidate.take_profit_price, candidate.stop_loss_price, candidate.units) == (
                native.target_price, native.tp_price, native.lc_price, native.units)
            assert candidate.direction == native.direction
            assert candidate.order_type == native.ls_type == "STOP"
            assert candidate.metadata["configured_risk_yen"] == 25
            assert intent.units == native.units <= policy.max_units
            assert intent.metadata["owner_tag"] == intent.metadata["origin"] == "resistance_breakout"
            assert intent.metadata["trade_timeout_enabled"] is True
            assert intent.trade_timeout_min == policy.trade_timeout_min
            assert intent.target_is_price and intent.take_profit_is_price and intent.stop_loss_is_price
    assert evaluation.diagnostics["analysis_name"] == "resistance_breakout"
    assert "signals" in evaluation.diagnostics["analysis"]


def test_selected_line_and_default_evaluation_match(main_source_directory):
    request = request_for()
    default = MainSourceAnalysis(source_directory=main_source_directory).evaluate(request)
    selected = MainSourceAnalysis(source_directory=main_source_directory, analysis_name="line").evaluate(request)
    assert default.candidates == selected.candidates
    assert default.intents == selected.intents
    assert default.diagnostics == selected.diagnostics
    assert default.order_context == selected.order_context


@pytest.mark.parametrize("plugin", [False, True])
@pytest.mark.parametrize("name", ["line", "resistance_breakout"])
def test_live_composition_uses_selected_checkpoint_identity(plugin, name, source_directory):
    from datetime import datetime
    from ogami_oanda.application.ports.position_state import CheckpointLoadResult, CheckpointLoadStatus
    from ogami_oanda.infrastructure.config.models import AppSettings, RuntimeAccountConfig
    from tests.fakes import FakeBroker, FakeMarketData, FakeNotifier, FixedClock, InMemoryTradeHistoryRepository

    saved = []
    repository = SimpleNamespace(load=lambda **kwargs: CheckpointLoadResult(CheckpointLoadStatus.MISSING), save=saved.append)
    broker = FakeBroker()
    settings = AppSettings({"primary": RuntimeAccountConfig("id", "unused", "practice")})
    ports = dict(market_data=FakeMarketData({}, {"USD_JPY": 150}), broker_execution=broker, broker_query=broker,
                 notifier=FakeNotifier(), history=InMemoryTradeHistoryRepository(), state_repository=repository,
                 clock=FixedClock(datetime(2026, 1, 2, 10)), main_analysis_dir=source_directory, analysis_name=name)
    if plugin:
        app = live.build_strategy_live_application(settings, OriginalStrategy(), "original-plugin", **ports)
        backend = app.strategy.analysis.analysis_backend
        base = "original-plugin"
    else:
        app = live.build_live_application(settings, **ports)
        backend = app.analysis.analysis_backend
        base = "builtin-line"
    assert backend.analysis_name == name
    assert app.portfolio.strategy_id == base + (":analysis=resistance_breakout" if name != "line" else "")
    assert saved[-1].strategy_id == app.portfolio.strategy_id
    assert not broker.requests and not broker.commands
