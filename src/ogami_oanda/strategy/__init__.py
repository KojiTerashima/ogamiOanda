"""Strategy ownership: original/, matcha/, shared/; see README.md for launching.

Historical module imports resolve to the canonical objects below. Keeping the
Matcha contracts import valid lets its Python/YAML bytes and checkpoint identity
survive this layout-only migration. New code should use owner-qualified imports.
"""

from importlib import import_module as _import_module
import sys as _sys

from .original.position_sizing import PositionSizingPolicy
from .shared.contracts import (
    StrategyCommand,
    StrategyCommandAction,
    StrategyDecision,
    StrategyInput,
    StrategyQuote,
    TradingStrategy,
)
from .shared.loader import LoadedStrategy, StrategyPluginError, load_strategy

# Register the contracts alias before a selected Matcha plugin is loaded.
# Alias child modules too so old/new imports never create different Enum/classes.
for _legacy_name, _canonical_name in {
    "contracts": "shared.contracts",
    "loader": "shared.loader",
    "position_sizing": "original.position_sizing",
    "line": "original.line",
    "position_management": "shared.position_management",
}.items():
    _module = _import_module(f"{__name__}.{_canonical_name}")
    globals()[_legacy_name] = _module
    _sys.modules[f"{__name__}.{_legacy_name}"] = _module
    _canonical_prefix = _module.__name__ + "."
    for _name, _child in tuple(_sys.modules.items()):
        if _name.startswith(_canonical_prefix):
            _suffix = _name[len(_module.__name__):]
            _sys.modules[f"{__name__}.{_legacy_name}{_suffix}"] = _child

__all__ = [
    "LoadedStrategy",
    "PositionSizingPolicy",
    "StrategyCommand",
    "StrategyCommandAction",
    "StrategyDecision",
    "StrategyInput",
    "StrategyPluginError",
    "StrategyQuote",
    "TradingStrategy",
    "load_strategy",
]
