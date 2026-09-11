"""Data-only boundary for evaluating unchanged main analysis sources."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping, Protocol

import pandas as pd

from ogami_oanda.domain.orders.models import OrderContext, OrderIntent


class MainAnalysisError(ValueError):
    """An invalid evaluation, distinct from an ordinary absence of signals."""


class AnalysisNotReady(MainAnalysisError):
    """Completed history or an explicitly required policy is unavailable."""


class AnalysisIntegrityError(MainAnalysisError):
    """The supplied history or result violates the upstream contract."""


class UnsupportedAnalysisDependency(MainAnalysisError):
    """The main source requested an unsupported dependency or API contract."""


@dataclass(frozen=True)
class AnalysisRequest:
    pair: str
    decision_time: object
    current_price: float
    candle_frames: Mapping[str, pd.DataFrame]
    mode: str = "inspection"
    evaluation_time: object | None = None
    usd_jpy_rate: float | None = None
    conversion_candles: pd.DataFrame | None = None
    source_granularities: Mapping[str, str] = field(default_factory=dict)
    risk_yen: float | None = None


@dataclass(frozen=True)
class AnalysisResult:
    analysis: str
    session_id: str
    result_id: str
    features: Mapping[str, object]
    diagnostics: Mapping[str, object] = field(default_factory=dict)
    status: str = "ok"


@dataclass(frozen=True)
class OrderCandidate:
    pair: str
    direction: int
    order_type: str
    target_price: float
    take_profit_price: float
    stop_loss_price: float
    units: int
    name: str
    priority: int
    order_timeout_min: int
    trade_timeout_min: int
    decision_time: str
    lc_change: tuple[Mapping[str, object], ...] = ()
    execution: str = "ready"
    metadata: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class PeakSnapshot:
    """The existing peak read surface, without an upstream class instance."""

    peaks_original: list[dict]
    skipped_peaks: list[dict]
    skipped_peaks_hard: list[dict]
    completed_df_r: pd.DataFrame


@dataclass(frozen=True)
class MainAnalysisEvaluation:
    intents: tuple[OrderIntent, ...]
    candidates: tuple[OrderCandidate, ...]
    frames: Mapping[str, pd.DataFrame]
    completed_frames: Mapping[str, pd.DataFrame]
    peaks: Mapping[str, PeakSnapshot]
    order_context: OrderContext
    diagnostics: Mapping[str, object]
    status: str = "ok"


class MainAnalysisBackend(Protocol):
    def evaluate(self, request: AnalysisRequest) -> MainAnalysisEvaluation: ...
