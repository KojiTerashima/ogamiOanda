"""Read supported Python sources directly from the caller's main directory."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Mapping

from ogami_oanda.domain.analysis.main_contracts import UnsupportedAnalysisDependency

DEFAULT_SOURCE_DIRECTORY = "../main"
SOURCE_MODULES = frozenset({
    "classCandleAnalysis", "classCandlePeaks", "classOanda", "classOrderCreate",
    "count2_flip_core", "count2_flip_workflow", "count2_resistance_sweep",
    "count2_target_grid_search", "test_win_point_usd_aud",
    "fCandleDataQuality", "fDoubleTopCore", "fFlipOrder", "fFlipPredictLive",
    "fFlipPredictPolicy", "fFootCountShape", "fGeneric", "fInspectionEquivalence",
    "fLineAnalysis", "fLineStrategyAudUsd", "fLineStrategyEurUsd",
    "fLineStrategyUsdJpy", "fResistanceBreakoutAnalysis", "fResistanceBreakoutCore",
    "fStairTrend", "f_ダブルトップ",
})
COMPAT_MODULES = frozenset({"tokens", "send_notice"})
EXTERNAL_MODULES = frozenset({"numpy", "pandas", "pytz", "plotly", "pympler", "requests", "oandapyV20"})


@dataclass(frozen=True)
class MainSources:
    """Immutable source bytes shared by evaluations of one backend."""

    directory: Path
    contents: Mapping[str, bytes]


def read_sources(source_directory: str | Path = DEFAULT_SOURCE_DIRECTORY) -> MainSources:
    """Read only supported code files, without Git, settings or generated files."""
    directory = Path(source_directory).expanduser().resolve()
    if not directory.is_dir():
        raise UnsupportedAnalysisDependency(f"main analysis directory does not exist: {directory}")
    contents = {}
    for name in sorted(SOURCE_MODULES):
        path = directory / f"{name}.py"
        try:
            contents[name] = path.read_bytes()
        except OSError as error:
            raise UnsupportedAnalysisDependency(f"cannot read main analysis source: {path} ({error.strerror})") from error
    return MainSources(directory, MappingProxyType(contents))
