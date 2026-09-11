"""Direct-source loading contracts that run without the external main repository."""

from dataclasses import is_dataclass
from pathlib import Path
from types import ModuleType, SimpleNamespace
import sys

import pytest

from ogami_oanda.adapters.legacy.main_analysis import MainSourceAnalysis, analyze
from ogami_oanda.adapters.legacy.main_analysis.loader import SourceRuntime
from ogami_oanda.adapters.legacy.main_analysis.orders import from_native_order
from ogami_oanda.adapters.legacy.main_analysis.source import SOURCE_MODULES, read_sources
from ogami_oanda.domain.analysis.main_contracts import AnalysisRequest, UnsupportedAnalysisDependency
from ogami_oanda.entrypoints import backtest, live
from ogami_oanda.entrypoints.main_analysis import bind_main_analysis
from ogami_oanda.strategy.original.strategy import OriginalStrategy


@pytest.fixture
def main_code(tmp_path):
    directory = tmp_path / "native main"
    directory.mkdir()
    for name in SOURCE_MODULES:
        (directory / f"{name}.py").write_text("")
    (directory / "fGeneric.py").write_text("value = 1\n")
    return directory


@pytest.fixture
def empty_request():
    return AnalysisRequest("USD_JPY", "2026-09-11 12:00:00", 150, {})


def test_default_directory_is_relative_to_working_directory(tmp_path, main_code, monkeypatch):
    main_code.rename(tmp_path / "main")
    working = tmp_path / "ogamiOanda"
    working.mkdir()
    monkeypatch.chdir(working)
    backend = MainSourceAnalysis()
    assert backend.source_directory == tmp_path / "main"
    # A frozen byte set cannot be independently edited through the public backend.
    with pytest.raises(TypeError):
        backend.sources.contents["fGeneric"] = b"value = 2"


def test_missing_directory_or_required_file_reports_its_path(tmp_path, main_code):
    missing = tmp_path / "absent main"
    with pytest.raises(UnsupportedAnalysisDependency) as error:
        MainSourceAnalysis(source_directory=missing)
    assert str(missing) in str(error.value)
    required = main_code / "fGeneric.py"
    required.unlink()
    with pytest.raises(UnsupportedAnalysisDependency) as error:
        MainSourceAnalysis(source_directory=main_code)
    assert str(required) in str(error.value)


def test_only_supported_code_is_read_and_nothing_is_written(main_code, monkeypatch):
    for name in ("tokens.py", "send_notice.py", "fAnalysis_order_Main.py", "fFlipWatch.py", "unrelated.py"):
        (main_code / name).write_text("raise AssertionError('must not execute')\n")
    expected = {path: path.read_bytes() for path in main_code.iterdir()}
    read_bytes = Path.read_bytes
    read_paths = []

    def read(path):
        read_paths.append(path)
        assert path.stem in SOURCE_MODULES
        return read_bytes(path)

    with monkeypatch.context() as patch:
        patch.setattr(Path, "read_bytes", read)
        sources = read_sources(main_code)
        with SourceRuntime(sources=sources) as runtime:
            assert runtime.load("fGeneric").value == 1
    assert set(read_paths) == {main_code / f"{name}.py" for name in SOURCE_MODULES}
    assert {path: path.read_bytes() for path in main_code.iterdir()} == expected
    assert not (main_code / "__pycache__").exists()


def test_source_changes_apply_only_to_new_backends(main_code, empty_request):
    running = MainSourceAnalysis(source_directory=main_code)
    (main_code / "fGeneric.py").write_text("value = 2\n")
    restarted = MainSourceAnalysis(source_directory=main_code)
    for backend, expected in ((running, 1), (restarted, 2), (running, 1)):
        with backend.evaluation(empty_request) as session:
            assert session.runtime.load("fGeneric").value == expected
    # Existing evaluations can still use the captured code if the directory disappears.
    main_code.rename(main_code.with_name("moved"))
    with running.evaluation(empty_request) as session:
        assert session.runtime.load("fGeneric").value == 1


def test_direct_imports_use_private_modules_and_actual_source_filenames(main_code):
    (main_code / "fDoubleTopCore.py").write_text(
        "from dataclasses import dataclass\nimport fGeneric\n"
        "@dataclass\nclass Result:\n    value: int = fGeneric.value\n"
    )
    before_path, before_stdout = list(sys.path), sys.stdout
    host = {name: sys.modules.get(name) for name in SOURCE_MODULES}
    with SourceRuntime(sources=read_sources(main_code)) as runtime:
        prefix = runtime.prefix
        module = runtime.load("fDoubleTopCore")
        assert is_dataclass(module.Result)
        assert module.Result().value == 1
        assert module.__file__ == str(main_code / "fDoubleTopCore.py")
        assert module.Result.__init__.__globals__["__name__"].startswith(prefix)
    assert list(sys.path) == before_path and sys.stdout is before_stdout
    assert all(sys.modules.get(name) is value for name, value in host.items())
    assert not any(name.startswith(prefix) for name in sys.modules)


@pytest.mark.parametrize("code", ["import unsupported_friend_module\n", "def broken(:\n"])
def test_bad_import_or_syntax_fails_explicitly_and_releases_namespace(code, main_code, monkeypatch):
    monkeypatch.setitem(sys.modules, "unsupported_friend_module", ModuleType("unsupported_friend_module"))
    (main_code / "fGeneric.py").write_text(code)
    with SourceRuntime(sources=read_sources(main_code)) as runtime:
        prefix = runtime.prefix
        with pytest.raises(UnsupportedAnalysisDependency):
            runtime.load("fGeneric")
        assert runtime.closed
    assert not any(name.startswith(prefix) for name in sys.modules)


def test_changed_function_arguments_and_order_schema_fail_explicitly(main_code, empty_request):
    (main_code / "fFootCountShape.py").write_text(
        "def foot_count2_shape_context(frame, peak, decision, pair, new_required_argument):\n    return {}\n"
    )
    backend = MainSourceAnalysis(source_directory=main_code)
    with backend.evaluation(empty_request) as session:
        context = SimpleNamespace(m5_completed_df_r=None, newest_m5_peak={}, decision_time=None, pair="USD_JPY")
        session._candles = SimpleNamespace(require_basic_analysis=lambda: context)
        with pytest.raises(UnsupportedAnalysisDependency, match="new_required_argument"):
            analyze(session, "shape")
    with pytest.raises(UnsupportedAnalysisDependency, match="missing"):
        from_native_order(SimpleNamespace(), "line")


def test_binding_uses_requested_directory_and_preserves_injected_dependencies(main_code, tmp_path):
    strategy = OriginalStrategy()
    backend = bind_main_analysis(strategy, mode="inspection", main_analysis_dir=main_code)
    assert backend.source_directory == main_code
    missing = tmp_path / "absent"
    assert bind_main_analysis(strategy, mode="live", main_analysis_dir=missing) is backend
    assert strategy.analysis.analysis_mode == "live"
    custom = OriginalStrategy(candidate_builder=lambda *args, **kwargs: [])
    assert bind_main_analysis(custom, mode="live", main_analysis_dir=missing) is None


@pytest.mark.parametrize("plugin", [False, True])
def test_missing_main_fails_live_composition_before_account_io(plugin, tmp_path):
    with pytest.raises(UnsupportedAnalysisDependency, match="absent"):
        if plugin:
            live.build_strategy_live_application(object(), OriginalStrategy(), "test", main_analysis_dir=tmp_path / "absent")
        else:
            live.build_live_application(object(), main_analysis_dir=tmp_path / "absent")


def test_backtest_selection_only_requires_main_for_original_run(main_code, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    arguments = ["--pair", "USD_JPY", "--from", "2026-09-11T00:00:00Z", "--to", "2026-09-11T00:01:00Z"]
    fetch = backtest.parser().parse_args(["fetch", *arguments, "--strategy", "original", "--data-dir", "unused", "--config", "unused"])
    strategy, _, _ = backtest.select_strategy(fetch)
    assert strategy.analysis.analysis_backend is None
    run_arguments = ["run", *arguments, "--mid-csv", "unused", "--initial-balance", "1000", "--output-dir", "unused"]
    matcha = backtest.parser().parse_args([*run_arguments, "--strategy", "matcha", "--main-analysis-dir", "absent"])
    assert type(backtest.select_strategy(matcha)[0]).__name__ == "MatchaStrategy"
    original = backtest.parser().parse_args([*run_arguments, "--strategy", "original", "--main-analysis-dir", str(main_code)])
    strategy, _, metadata = backtest.select_strategy(original)
    assert strategy.analysis.analysis_backend.source_directory == main_code
    assert "main_source_commit" not in metadata
    original.main_analysis_dir = "absent"
    with pytest.raises(UnsupportedAnalysisDependency):
        backtest.select_strategy(original)


def test_live_cli_forwards_main_directory_and_smoke_ignores_it(main_code, monkeypatch, capsys):
    from ogami_oanda.application.services.position_portfolio_service import RegistrationResult
    calls = []
    monkeypatch.setattr(live, "load_settings", lambda path: object())

    def build(settings, **kwargs):
        calls.append(kwargs)
        return SimpleNamespace(run_resilient_once=lambda **kwargs: live.LiveRunResult(None, RegistrationResult((), ())))

    monkeypatch.setattr(live, "build_live_application", build)
    assert live.main(["--config", "unused", "--main-analysis-dir", str(main_code), "--dry-run", "--once"]) == 0
    assert calls[0]["main_analysis_dir"] == str(main_code)
    assert live.main(["--offline-smoke", "--dry-run", "--once", "--main-analysis-dir", "absent"]) == 0
    assert len(calls) == 1
    assert "accepted=" in capsys.readouterr().out


def test_compiled_code_keeps_each_directory_in_tracebacks(main_code, tmp_path):
    other = tmp_path / "another main"
    other.mkdir()
    code = b"def answer():\n    return 42\n"
    for directory in (main_code, other):
        for name in SOURCE_MODULES:
            (directory / f"{name}.py").write_bytes(code)
        with SourceRuntime(sources=read_sources(directory)) as runtime:
            module = runtime.load("fGeneric")
            assert module.answer() == 42
            assert module.answer.__code__.co_filename == str(directory / "fGeneric.py")


def test_python_backtest_api_binds_directory_and_records_path(main_code, tmp_path):
    from datetime import datetime, timedelta, timezone
    import json
    from ogami_oanda.domain.market.history import HistoricalCandle, OHLC
    from ogami_oanda.entrypoints.backtest_run import run_backtest
    from ogami_oanda.strategy.shared.contracts import StrategyDecision

    class QuietOriginal(OriginalStrategy):
        data_requirements = {}

        def decide(self, input):
            return StrategyDecision()

    strategy = QuietOriginal()
    start = datetime(2026, 9, 11, tzinfo=timezone.utc)
    price = OHLC(150, 150, 150, 150)
    candle = HistoricalCandle(start, price, price, price)
    output = tmp_path / "report"
    metadata = {"fixture": True}
    run_backtest(strategy, "quiet-original", "USD_JPY", [candle], start, start + timedelta(seconds=5),
                 initial_balance=10000, output_dir=output, main_analysis_dir=main_code, metadata=metadata)
    assert strategy.analysis.analysis_backend.source_directory == main_code
    report = json.loads((output / "run.json").read_text())
    assert report["main_source_directory"] == str(main_code)
    assert "main_source_commit" not in report
    assert metadata == {"fixture": True}
