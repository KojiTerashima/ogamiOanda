from __future__ import annotations

import importlib
from datetime import datetime, timezone
from pathlib import Path

import pytest


def _loader_module():
    return importlib.import_module("ogami_oanda.strategy.loader")


def _plugin_directory() -> Path:
    return Path(importlib.import_module("ogami_oanda.strategy").__file__).parent


def _write_plugin(directory: Path, name: str, source: str, yaml_text: str) -> tuple[Path, Path]:
    python_path = directory / f"{name}.py"
    yaml_path = directory / f"{name}.yaml"
    python_path.write_text(source, encoding="utf-8")
    yaml_path.write_text(yaml_text, encoding="utf-8")
    return python_path, yaml_path


def test_loader_requires_matching_api_version_before_factory_invocation(tmp_path: Path):
    loader = _loader_module()
    plugin_path, yaml_path = _write_plugin(
        _plugin_directory(),
        "_test_wrong_api_version",
        "STRATEGY_API_VERSION = 2\n\ndef create_strategy(config):\n    raise AssertionError('factory must not run')\n",
        "pair: USD_JPY\n",
    )
    try:
        with pytest.raises(loader.StrategyPluginError, match="STRATEGY_API_VERSION.*1"):
            loader.load_strategy(plugin_path, yaml_path)
    finally:
        plugin_path.unlink(missing_ok=True)
        yaml_path.unlink(missing_ok=True)


def test_loader_requires_factory_to_return_trading_strategy(tmp_path: Path):
    loader = _loader_module()
    plugin_path, yaml_path = _write_plugin(
        _plugin_directory(),
        "_test_invalid_factory_result",
        "STRATEGY_API_VERSION = 1\n\ndef create_strategy(config):\n    return object()\n",
        "pair: USD_JPY\n",
    )
    try:
        with pytest.raises(loader.StrategyPluginError, match="TradingStrategy"):
            loader.load_strategy(plugin_path, yaml_path)
    finally:
        plugin_path.unlink(missing_ok=True)
        yaml_path.unlink(missing_ok=True)


@pytest.mark.parametrize("yaml_text", ["- not\n- a mapping\n", "null\n"])
def test_loader_requires_yaml_top_level_mapping(yaml_text: str):
    loader = _loader_module()
    plugin_path, yaml_path = _write_plugin(
        _plugin_directory(),
        "_test_invalid_yaml",
        "STRATEGY_API_VERSION = 1\n\ndef create_strategy(config):\n    return None\n",
        yaml_text,
    )
    try:
        with pytest.raises(loader.StrategyPluginError, match="top level.*mapping"):
            loader.load_strategy(plugin_path, yaml_path)
    finally:
        plugin_path.unlink(missing_ok=True)
        yaml_path.unlink(missing_ok=True)


def test_loader_rejects_python_path_outside_strategy_package(tmp_path: Path):
    loader = _loader_module()
    plugin_path = tmp_path / "outside.py"
    plugin_path.write_text("STRATEGY_API_VERSION = 1\n", encoding="utf-8")
    yaml_path = _plugin_directory() / "_test_valid_config.yaml"
    yaml_path.write_text("pair: USD_JPY\n", encoding="utf-8")
    try:
        with pytest.raises(loader.StrategyPluginError, match="strategy Python.*within"):
            loader.load_strategy(plugin_path, yaml_path)
    finally:
        yaml_path.unlink(missing_ok=True)


def test_loader_rejects_yaml_path_outside_strategy_package(tmp_path: Path):
    loader = _loader_module()
    plugin_path = _plugin_directory() / "_test_valid_plugin.py"
    plugin_path.write_text("STRATEGY_API_VERSION = 1\n", encoding="utf-8")
    yaml_path = tmp_path / "outside.yaml"
    yaml_path.write_text("pair: USD_JPY\n", encoding="utf-8")
    try:
        with pytest.raises(loader.StrategyPluginError, match="strategy YAML.*within"):
            loader.load_strategy(plugin_path, yaml_path)
    finally:
        plugin_path.unlink(missing_ok=True)


def test_loader_resolves_paths_from_cwd_and_hashes_plugin_contents_deterministically(monkeypatch: pytest.MonkeyPatch):
    loader = _loader_module()
    package_dir = _plugin_directory()
    plugin_path, yaml_path = _write_plugin(
        package_dir,
        "_test_valid_plugin",
        "from ogami_oanda.strategy.contracts import StrategyDecision\n\nSTRATEGY_API_VERSION = 1\n\nclass Plugin:\n    def decide(self, input): return StrategyDecision()\n    def dump_state(self): return {}\n    def load_state(self, state): pass\n\ndef create_strategy(config): return Plugin()\n",
        "pair: USD_JPY\n",
    )
    monkeypatch.chdir(package_dir.parent)
    try:
        first = loader.load_strategy("strategy/_test_valid_plugin.py", "strategy/_test_valid_plugin.yaml")
        second = loader.load_strategy(plugin_path, yaml_path)
        assert first.strategy_id == second.strategy_id
        assert first.strategy_id.startswith("strategy-")
        assert len(first.strategy_id) > len("strategy-")
        yaml_path.write_text("pair: EUR_USD\n", encoding="utf-8")
        assert loader.load_strategy(plugin_path, yaml_path).strategy_id != first.strategy_id
    finally:
        plugin_path.unlink(missing_ok=True)
        yaml_path.unlink(missing_ok=True)


def test_loader_supports_dataclass_decorated_plugin():
    loader = _loader_module()
    plugin_path, yaml_path = _write_plugin(
        _plugin_directory(),
        "_test_dataclass_plugin",
        "from __future__ import annotations\n\nfrom dataclasses import dataclass\n\nfrom ogami_oanda.strategy.contracts import StrategyDecision\n\nSTRATEGY_API_VERSION = 1\n\n@dataclass\nclass Plugin:\n    pair: str\n\n    def decide(self, input): return StrategyDecision()\n    def dump_state(self): return {}\n    def load_state(self, state): pass\n\ndef create_strategy(config): return Plugin(config['pair'])\n",
        "pair: USD_JPY\n",
    )
    try:
        loaded = loader.load_strategy(plugin_path, yaml_path)

        assert loaded.strategy.pair == "USD_JPY"
    finally:
        plugin_path.unlink(missing_ok=True)
        yaml_path.unlink(missing_ok=True)


def test_market_quote_accepts_omitted_source_time_and_oanda_quote_uses_aware_price_time():
    from ogami_oanda.adapters.oanda.mappers import map_price_response
    from ogami_oanda.application.ports.market_data import MarketQuote

    assert MarketQuote("USD_JPY", 150.1, 150.2, 150.15).source_time is None
    mapped = map_price_response(
        "USD_JPY",
        {
            "prices": [
                {
                    "time": "2026-01-02T00:00:00.000000000Z",
                    "bids": [{"price": "150.10"}],
                    "asks": [{"price": "150.12"}],
                }
            ]
        },
    )

    assert mapped["source_time"] == datetime(2026, 1, 2, tzinfo=timezone.utc)
    assert mapped["source_time"].tzinfo is not None
