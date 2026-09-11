"""The original line strategy through the shared, broker-neutral API v1."""

from __future__ import annotations

from math import isfinite
from typing import Mapping

from ogami_oanda.domain.analysis.main_contracts import MainAnalysisBackend
from ogami_oanda.strategy.original.analysis import (
    CandidateBuilder,
    CandidateContextBuilder,
    MarketAnalysisResult,
    OriginalAnalysis,
)
from ogami_oanda.strategy.original.context import build_line_candidate_context
from ogami_oanda.strategy.original.line import LineCandidateBuilder
from ogami_oanda.strategy.shared.contracts import (
    JSONState,
    JSONValue,
    StrategyCandleProtection,
    StrategyDecision,
    StrategyInput,
)

STRATEGY_API_VERSION = 1


class OriginalStrategy:
    """Pure multi-frame decisions; scheduling and broker state stay with callers."""

    evaluation_profile = "original"
    data_requirements = {"M5": 250, "H1": 250, "M30": 250, "S5": 250}

    def __init__(
        self,
        pair: str = "USD_JPY",
        risk_yen: float = 500,
        line_units: int = 1,
        *,
        candidate_builder: CandidateBuilder | None = None,
        candidate_context_builder: CandidateContextBuilder | None = build_line_candidate_context,
        _analysis: OriginalAnalysis | None = None,
        analysis_backend: MainAnalysisBackend | None = None,
    ) -> None:
        if pair not in {"USD_JPY", "EUR_USD", "AUD_USD"}:
            raise ValueError("original strategy pair must be USD_JPY, EUR_USD, or AUD_USD")
        if isinstance(risk_yen, bool) or not isinstance(risk_yen, (int, float)) or not isfinite(risk_yen) or risk_yen <= 0:
            raise ValueError("original strategy risk_yen must be positive and finite")
        if type(line_units) is not int or line_units <= 0:
            raise ValueError("original strategy line_units must be a positive integer")
        self.pair = pair
        self._use_main_analysis_default = candidate_builder is None and _analysis is None
        self.analysis = _analysis or OriginalAnalysis(
            candidate_builder or LineCandidateBuilder(pair, risk_yen=risk_yen),
            candidate_context_builder=candidate_context_builder,
            units=line_units,
        )
        self.risk_yen = risk_yen
        if analysis_backend is not None:
            self.bind_main_analysis(analysis_backend)
        self.last_analysis: MarketAnalysisResult | None = None

    def bind_main_analysis(self, backend: MainAnalysisBackend, *, mode: str = "inspection") -> None:
        self.analysis.analysis_backend = backend
        self.analysis.analysis_mode = mode
        self.analysis.risk_yen = self.risk_yen

    def decide(self, input: StrategyInput) -> StrategyDecision:
        if input.quote.pair != self.pair:
            raise ValueError(f"original strategy configured for {self.pair}, got {input.quote.pair}")
        missing = self.data_requirements.keys() - input.candle_frames.keys()
        if missing:
            raise ValueError(f"original strategy requires candle frames: {', '.join(sorted(missing))}")
        decision_time = input.decision_time or (
            input.evaluation_time.isoformat()
            if input.evaluation_time is not None
            else str(input.candle_frames["M5"].iloc[0]["time_jp"])
        )
        clock_arguments = ({"evaluation_time": input.evaluation_time}
                           if getattr(self.analysis, "analysis_backend", None) is not None else {})
        result = self.analysis.analyze_frames(
            self.pair, decision_time,
            current_price=input.quote.mid,
            candle_frames=input.candle_frames,
            **clock_arguments,
        )
        self.last_analysis = result
        frame = result.completed_frames.get("M5")
        if frame is not None:
            peaks = result.peaks["M5"].peaks_original
            protection = (StrategyCandleProtection(dict(peaks[0]), frame.iloc[0].to_dict())
                          if len(frame) and peaks else None)
        else:
            frame = result.frames.get("M5")
            peaks = result.peaks["M5"].peaks_original if "M5" in result.peaks else []
            protection = (StrategyCandleProtection(dict(peaks[0]), frame.iloc[1].to_dict())
                          if frame is not None and len(frame) >= 2 and peaks else None)
        diagnostics = result.candidate_diagnostics
        return StrategyDecision(
            intents=result.intents,
            order_context=result.order_context,
            candle_protection=protection,
            diagnostics={
                **({"main_analysis": result.candidate_context["main_analysis"]}
                   if "main_analysis" in result.candidate_context else {}),
                "raw_counts": dict(diagnostics.raw_counts),
                "selected_counts": dict(diagnostics.selected_counts),
                "rejected_reasons": {key: dict(value) for key, value in diagnostics.rejected_reasons.items()},
            } if diagnostics is not None else {},
        )

    def dump_state(self) -> JSONState:
        return {}

    def load_state(self, state: Mapping[str, JSONValue]) -> None:
        if not isinstance(state, Mapping) or state:
            raise ValueError("original strategy state must be an empty mapping")
        self.last_analysis = None


def create_strategy(config: Mapping[str, object]) -> OriginalStrategy:
    allowed = {"pair", "risk_yen", "line_units"}
    unknown = set(config) - allowed
    if unknown:
        raise ValueError(f"unsupported original strategy parameters: {', '.join(sorted(unknown))}")
    return OriginalStrategy(**dict(config))
