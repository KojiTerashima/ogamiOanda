"""Evaluation lifetime and native result ownership."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

from ogami_oanda.domain.analysis.main_contracts import (
    AnalysisIntegrityError, AnalysisNotReady, AnalysisResult, MainAnalysisError, UnsupportedAnalysisDependency,
)

from .inputs import jst_time, prepare_candles
from .loader import SourceRuntime


class AnalysisSession:
    def __init__(self, request, *, sources=None, artifact_directory: Path | None = None):
        self.request = request
        self.runtime = SourceRuntime(sources=sources,
                                     evaluation_time=jst_time(request.evaluation_time or request.decision_time).to_pydatetime(),
                                     artifact_directory=artifact_directory)
        self.id = self.runtime.prefix
        self._candles = None
        self.frames = {}
        self.native_results = {}
        self.completed_orders = {}
        self.control_events = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.native_results.clear()
        self.completed_orders.clear()
        self.control_events.clear()
        self._candles = None
        self.runtime.close()

    @contextmanager
    def translated_errors(self):
        try:
            yield
        except MainAnalysisError:
            raise
        except Exception as error:
            name = type(error).__name__
            if name in {"CandleHistoryNotReady", "LiveDataNotReady"} or str(error).startswith("no candle is completed"):
                raise AnalysisNotReady(str(error)) from error
            if isinstance(error, ValueError) or name in {"LiveDataIntegrityError", "LiveDataError"}:
                raise AnalysisIntegrityError(str(error)) from error
            if isinstance(error, (TypeError, AttributeError, KeyError)):
                raise UnsupportedAnalysisDependency(
                    f"incompatible main analysis API in {self.runtime.source_directory}: {type(error).__name__}: {error}"
                ) from error
            raise

    @property
    def candles(self):
        if self.runtime.closed:
            raise RuntimeError("analysis session is closed")
        if self._candles is None:
            with self.translated_errors():
                self._candles, self.frames = prepare_candles(self.runtime, self.request)
        return self._candles

    def store(self, name, native, features, *, status="ok"):
        key = uuid4().hex
        result = AnalysisResult(name, self.id, key, features,
                                {"source_directory": str(self.runtime.source_directory),
                                 "messages": tuple(self.runtime.messages)}, status)
        self.native_results[key] = (result, native)
        return result

    def native(self, result):
        if self.runtime.closed:
            raise RuntimeError("analysis session is closed")
        entry = self.native_results.get(result.result_id)
        if result.session_id != self.id or entry is None or entry[0] is not result:
            raise AnalysisIntegrityError("analysis result belongs to another evaluation")
        return entry[1]
