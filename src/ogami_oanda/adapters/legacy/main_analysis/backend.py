"""Compose native evaluation stages behind the domain analysis port."""

from __future__ import annotations

from pathlib import Path

from ogami_oanda.domain.analysis.main_contracts import (
    AnalysisNotReady, MainAnalysisEvaluation, PeakSnapshot,
)
from ogami_oanda.domain.analysis.main_orders import to_order_intents
from ogami_oanda.domain.orders.models import OrderContext

from .analysis import analyze
from .inputs import jst_time, peak_objects
from .orders import build_order_candidates
from .session import AnalysisSession
from .source import DEFAULT_SOURCE_DIRECTORY, read_sources
from .values import plain


class MainSourceAnalysis:
    """Read main once; mutable execution state belongs to individual evaluations."""

    def __init__(self, *, source_directory: str | Path = DEFAULT_SOURCE_DIRECTORY,
                 artifact_directory: str | Path | None = None):
        self.sources = read_sources(source_directory)
        self.artifact_directory = Path(artifact_directory).resolve() if artifact_directory is not None else None

    @property
    def source_directory(self):
        return self.sources.directory

    def evaluation(self, request):
        """Open the session shared by analyze and build_order_candidates."""
        return AnalysisSession(request, sources=self.sources, artifact_directory=self.artifact_directory)

    def evaluate(self, request):
        """Compose the currently enabled original line strategy for the domain port."""
        with self.evaluation(request) as session:
            try:
                result = analyze(session, "line")
                candidates = build_order_candidates(session, result)
            except AnalysisNotReady as error:
                return MainAnalysisEvaluation(
                    (), (), {}, {}, {},
                    OrderContext(request.current_price, jst_time(request.decision_time).strftime("%Y/%m/%d %H:%M:%S")),
                    {"status": "not_ready", "reason": str(error), "source_directory": str(self.source_directory)},
                    status="not_ready",
                )
            candles = session.candles
            peaks = {
                name: PeakSnapshot(plain(item.peaks_original), plain(item.skipped_peaks),
                                   plain(item.skipped_peaks_hard), item.completed_df_r.copy(deep=True))
                for name, item in peak_objects(candles).items()
            }
            completed = {name: peak.completed_df_r for name, peak in peaks.items()}
            if candles.s5_completed_df_r is not None:
                completed["S5"] = candles.s5_completed_df_r.copy(deep=True)
            context = OrderContext(request.current_price, candles.decision_time.strftime("%Y/%m/%d %H:%M:%S"),
                                   float(candles.candle_meta_class.cal_move_ave(1)))
            intents = to_order_intents(candidates)
            return MainAnalysisEvaluation(
                intents, candidates, {name: frame.copy(deep=True) for name, frame in session.frames.items()},
                completed, peaks, context,
                {"source_directory": str(self.source_directory), "analysis": plain(result.features),
                 "candidate_count": len(candidates), "intent_count": len(intents),
                 "withheld": [candidate.execution for candidate in candidates if candidate.execution != "ready"],
                 "unsupported_controls": tuple(session.control_events),
                 "messages": tuple(session.runtime.messages)},
            )
