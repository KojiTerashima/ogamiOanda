"""Provenance follows executed bytes, independently of mutable source paths."""

import csv
from datetime import timedelta
import hashlib
from importlib.metadata import version
import json
from pathlib import Path
import platform
from types import SimpleNamespace

import pytest

from ogami_oanda.adapters.legacy.main_analysis.backend import MainSourceAnalysis
from ogami_oanda.adapters.legacy.main_analysis.source import MainSources, SOURCE_MODULES
from ogami_oanda.domain.analysis.main_contracts import AnalysisRequest
from ogami_oanda.entrypoints import backtest, backtest_run
from tests.test_backtest_run import ExampleStrategy, START, candles


@pytest.fixture
def source_directory(tmp_path):
    directory = tmp_path / "main"
    directory.mkdir()
    for name in SOURCE_MODULES:
        (directory / f"{name}.py").write_text("# fixture\n", encoding="utf-8")
    (directory / "fGeneric.py").write_text("value = 1\n", encoding="utf-8")
    return directory


def test_source_manifest_is_canonical_and_detached_from_paths_and_input_mutations(tmp_path):
    contents = {"z": b"value = 1\n", "a_日本語": "# 日本語\n".encode()}
    sources = MainSources(tmp_path / "one", contents)
    expected = {"schema_version": 1, "files": [
        {"path": f"{name}.py", "size_bytes": len(contents[name]),
         "sha256": hashlib.sha256(contents[name]).hexdigest()}
        for name in sorted(contents)
    ]}
    payload = json.dumps(expected, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    assert sources.manifest == expected
    assert sources.sha256 == hashlib.sha256(payload).hexdigest()
    assert sources.sha256 == MainSources(tmp_path / "two", dict(reversed(list(contents.items())))).sha256
    original_digest = sources.sha256
    contents["z"] = b"value = 2\n"
    assert sources.contents["z"] == b"value = 1\n"
    assert MainSources(tmp_path, contents).sha256 != original_digest
    assert MainSources(tmp_path, {**contents, "extra": b""}).sha256 != MainSources(tmp_path, contents).sha256
    changed = sources.manifest
    changed["files"][0]["sha256"] = "forged"
    assert sources.manifest == expected
    assert sources.sha256 == original_digest


def test_backend_provenance_stays_with_executed_snapshot_without_reads_or_hashing(source_directory, monkeypatch):
    from ogami_oanda.adapters.legacy.main_analysis import source

    backend = MainSourceAnalysis(source_directory=source_directory)
    before = backend.source_sha256
    manifest = backend.source_manifest
    assert {entry["path"] for entry in manifest["files"]} == {f"{name}.py" for name in SOURCE_MODULES}
    (source_directory / "tokens.py").write_text("must_not_be_read = True\n")
    assert MainSourceAnalysis(source_directory=source_directory).source_sha256 == before
    (source_directory / "fGeneric.py").write_text("value = 2\n")
    updated = MainSourceAnalysis(source_directory=source_directory)
    assert updated.source_sha256 != before
    source_directory.rename(source_directory.with_name("moved"))

    def forbidden(*args, **kwargs):
        raise AssertionError("evaluation must use already hashed source bytes")

    monkeypatch.setattr(Path, "read_bytes", forbidden)
    monkeypatch.setattr(source.hashlib, "sha256", forbidden)
    request = AnalysisRequest("USD_JPY", START, 150, {})
    for target, value in ((backend, 1), (updated, 2), (backend, 1)):
        with target.evaluation(request) as session:
            assert session.runtime.load("fGeneric").value == value
    assert backend.source_manifest == manifest
    assert backend.source_sha256 == before


class BoundStrategy(ExampleStrategy):
    """Exercise shared replay with the same injected native source lifetime."""

    def __init__(self, backend):
        super().__init__()
        self.analysis = SimpleNamespace(analysis_backend=backend)

    def bind_main_analysis(self, backend, *, mode):
        assert self.analysis.analysis_backend is backend


def assert_recorded_provenance(metadata, backend):
    assert metadata["main_source_manifest"] == backend.source_manifest
    assert metadata["main_source_sha256"] == backend.source_sha256
    environment = metadata["runtime_versions"]
    assert environment["python"] == {"implementation": platform.python_implementation(), "version": platform.python_version()}
    assert environment["platform"]["system"] == platform.system()
    assert environment["platform"]["machine"] == platform.machine()
    for package in ("numpy", "oandapyV20", "pandas", "plotly", "pympler", "pytz", "PyYAML", "requests"):
        assert environment["packages"][package] == version(package)


@pytest.mark.parametrize("failure", [False, True])
def test_api_records_running_and_terminal_provenance_and_rejects_metadata_spoofing(tmp_path, source_directory, failure):
    backend = MainSourceAnalysis(source_directory=source_directory)
    strategy = BoundStrategy(backend)
    output = tmp_path / "result"
    forged = {"main_source_manifest": {}, "main_source_sha256": "forged", "runtime_versions": {},
              "main_source_directory": "forged", "source_sha256": "existing-package-hash"}

    def values():
        running = json.loads((output / "run.json").read_text())
        assert running["status"] == "running"
        assert_recorded_provenance(running, backend)
        (source_directory / "fGeneric.py").write_text("value = 3\n")
        for candle in candles():
            if failure and candle.time == START + timedelta(seconds=10):
                raise RuntimeError("fixture replay failure")
            yield candle

    def run():
        return backtest_run.run_backtest(strategy, "existing-id", "USD_JPY", values(), START,
                                         START + timedelta(minutes=1), initial_balance=10000,
                                         output_dir=output, metadata=forged)

    if failure:
        with pytest.raises(RuntimeError, match="fixture replay failure"):
            run()
    else:
        run()
    final = json.loads((output / "run.json").read_text())
    assert final["status"] == ("failed" if failure else "complete")
    assert_recorded_provenance(final, backend)
    assert final["strategy_id"] == "existing-id"
    assert final["source_sha256"] == "existing-package-hash"
    assert final["main_source_directory"] == str(backend.source_directory)
    assert forged["main_source_sha256"] == "forged"


@pytest.mark.parametrize("failure", [False, True])
def test_cli_and_api_record_identical_provenance(tmp_path, source_directory, monkeypatch, failure):
    backend = MainSourceAnalysis(source_directory=source_directory)
    source = tmp_path / "mid.csv"
    with source.open("w", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["time", "open", "high", "low", "close"])
        for candle in candles():
            writer.writerow([candle.time.isoformat(), candle.mid.open, candle.mid.high, candle.mid.low, candle.mid.close])
    monkeypatch.setattr(backtest, "select_strategy", lambda args: (BoundStrategy(backend), "test", {}))
    if failure:
        def fail_decision(self, input):
            raise RuntimeError("fixture decision failure")

        monkeypatch.setattr(BoundStrategy, "decide", fail_decision)
    cli_output = tmp_path / "cli"
    assert backtest.main(["run", "--strategy", "original", "--pair", "USD_JPY", "--from", START.isoformat(),
                          "--to", (START + timedelta(minutes=1)).isoformat(), "--mid-csv", str(source),
                          "--fixed-spread-pips", "0", "--initial-balance", "10000", "--output-dir", str(cli_output)]) == int(failure)
    api_output = tmp_path / "api"

    def run_api():
        backtest_run.run_backtest(BoundStrategy(backend), "test", "USD_JPY", candles(), START,
                                  START + timedelta(minutes=1), initial_balance=10000, output_dir=api_output)

    if failure:
        with pytest.raises(RuntimeError, match="fixture decision failure"):
            run_api()
    else:
        run_api()
    cli = json.loads((cli_output / "run.json").read_text())
    api = json.loads((api_output / "run.json").read_text())
    assert_recorded_provenance(cli, backend)
    assert cli["status"] == api["status"] == ("failed" if failure else "complete")
    for key in ("main_source_manifest", "main_source_sha256", "runtime_versions"):
        assert cli[key] == api[key]


@pytest.mark.parametrize("custom_backend", [False, True])
def test_non_main_strategies_omit_forged_main_metadata(tmp_path, monkeypatch, custom_backend):
    def forbidden(*args, **kwargs):
        raise AssertionError("non-main strategy must not read main")

    monkeypatch.setattr(Path, "read_bytes", forbidden)
    strategy = BoundStrategy(SimpleNamespace()) if custom_backend else ExampleStrategy()
    output = tmp_path / "result"
    backtest_run.run_backtest(strategy, "test", "USD_JPY", candles(), START, START + timedelta(minutes=1),
                              initial_balance=10000, output_dir=output,
                              metadata={"main_source_manifest": {}, "main_source_sha256": "forged", "runtime_versions": {}})
    metadata = json.loads((output / "run.json").read_text())
    assert "main_source_manifest" not in metadata
    assert "main_source_sha256" not in metadata
    assert metadata["runtime_versions"]["python"]["version"] == platform.python_version()
