"""Load trusted local Python-and-YAML strategy plugins from this package."""

from __future__ import annotations

import hashlib
import importlib.util
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Mapping

import yaml

from ogami_oanda.strategy.contracts import TradingStrategy

STRATEGY_API_VERSION = 1


class StrategyPluginError(ValueError):
    """An actionable configuration error that prevents strategy startup."""


@dataclass(frozen=True)
class LoadedStrategy:
    strategy: TradingStrategy
    config: Mapping[str, object]
    strategy_id: str
    python_path: Path
    yaml_path: Path


def load_strategy(strategy_py: str | Path, strategy_yaml: str | Path) -> LoadedStrategy:
    """Validate and instantiate one trusted package-local strategy plugin."""

    python_path = _resolve_package_path(strategy_py, "strategy Python")
    yaml_path = _resolve_package_path(strategy_yaml, "strategy YAML")
    config = _load_config(yaml_path)
    module = _load_module(python_path)
    _validate_api(module, python_path)

    factory = module.create_strategy
    try:
        strategy = factory(config)
    except Exception as exc:
        raise StrategyPluginError(
            f"strategy factory in {python_path} failed: {exc}"
        ) from exc
    if not isinstance(strategy, TradingStrategy):
        raise StrategyPluginError(
            f"strategy factory in {python_path} must return a TradingStrategy"
        )

    return LoadedStrategy(
        strategy=strategy,
        config=config,
        strategy_id=_strategy_id(python_path, yaml_path),
        python_path=python_path,
        yaml_path=yaml_path,
    )


def _resolve_package_path(value: str | Path, label: str) -> Path:
    path = Path(value).expanduser().resolve()
    package_dir = Path(__file__).resolve().parent
    try:
        path.relative_to(package_dir)
    except ValueError as exc:
        raise StrategyPluginError(
            f"{label} path must resolve within {package_dir}: {path}"
        ) from exc
    if not path.is_file():
        raise StrategyPluginError(f"{label} path is not a file: {path}")
    return path


def _load_config(yaml_path: Path) -> dict[str, object]:
    try:
        parsed = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise StrategyPluginError(f"could not read strategy YAML {yaml_path}: {exc}") from exc
    except yaml.YAMLError as exc:
        raise StrategyPluginError(f"invalid strategy YAML {yaml_path}: {exc}") from exc
    if not isinstance(parsed, Mapping):
        raise StrategyPluginError("strategy YAML top level must be a mapping")
    if not all(isinstance(key, str) for key in parsed):
        raise StrategyPluginError("strategy YAML mapping keys must be strings")
    return dict(parsed)


def _load_module(python_path: Path) -> ModuleType:
    module_name = f"ogami_oanda.strategy._plugin_{_content_hash(python_path)[:16]}"
    spec = importlib.util.spec_from_file_location(module_name, python_path)
    if spec is None or spec.loader is None:
        raise StrategyPluginError(f"could not import strategy Python {python_path}")
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception as exc:
        raise StrategyPluginError(f"could not import strategy Python {python_path}: {exc}") from exc
    return module


def _validate_api(module: ModuleType, python_path: Path) -> None:
    version = getattr(module, "STRATEGY_API_VERSION", None)
    if type(version) is not int or version != STRATEGY_API_VERSION:
        raise StrategyPluginError(
            f"strategy Python {python_path} must define STRATEGY_API_VERSION = {STRATEGY_API_VERSION}"
        )
    if not callable(getattr(module, "create_strategy", None)):
        raise StrategyPluginError(
            f"strategy Python {python_path} must define create_strategy(config)"
        )


def _strategy_id(python_path: Path, yaml_path: Path) -> str:
    return f"strategy-{_content_hash(python_path)[:16]}-{_content_hash(yaml_path)[:16]}"


def _content_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
