"""Analysis-only entry points; order construction lives in orders.py."""

from __future__ import annotations

from dataclasses import replace

from ogami_oanda.domain.analysis.main_contracts import (
    AnalysisNotReady, UnsupportedAnalysisDependency,
)

from .inputs import jst_time, line_view, peak_objects
from .values import plain

ANALYSES = frozenset({"candles", "line", "shape", "stair", "double_top", "resistance_breakout", "flip"})


def policy_from(module, parameters):
    return replace(module.LIVE_TRIAL_POLICY_V1, **dict(parameters)) if parameters else module.LIVE_TRIAL_POLICY_V1


def analyze(session, name: str, parameters=None):
    """Run native detection and detach facts; retain native objects in the session."""
    if name not in ANALYSES:
        raise UnsupportedAnalysisDependency(f"unsupported analysis: {name}")
    parameters = dict(parameters or {})
    with session.translated_errors():
        candles = session.candles
        context = candles.require_basic_analysis()
        runtime = session.runtime
        if name == "candles":
            if parameters:
                raise ValueError("candle preparation uses the evaluation request")
            features = {key: {"peaks": plain(value.peaks_original),
                              "completed_frame": value.completed_df_r.copy(deep=True),
                              "quality": plain(value.completed_df_r.attrs)}
                        for key, value in peak_objects(candles).items()}
            return session.store(name, None, features)
        if name == "line":
            if parameters:
                raise ValueError("line analysis uses the original pair profile; use order risk settings")
            view = line_view(runtime, session.request, candles)
            module = runtime.load("fLineAnalysis")
            lines = {(foot, count): module.LineStrengthCal(candles, foot, count)
                     for foot, count in (("m5", 60), ("m5", 30), ("h1", 65), ("h1", 30))}
            features = {f"{foot}_{count}": plain(line.all_lines) for (foot, count), line in lines.items()}
            return session.store(name, {"view": view, "lines": lines}, features)
        if name == "shape":
            module = runtime.load("fFootCountShape")
            features = module.foot_count2_shape_context(
                context.m5_completed_df_r, context.newest_m5_peak, context.decision_time, context.pair, **parameters)
            return session.store(name, None, plain(features))
        if name == "stair":
            module = runtime.load("fStairTrend")
            features = {
                "M5": module.detect_m5_stair_trend(context.m5_peaks_class.peaks_original, context.pair,
                                                  context.m5_completed_df_r, **parameters),
                "H1": module.detect_h1_stair_trend(context.h1_peaks_class.peaks_original, context.pair,
                                                  context.h1_completed_df_r, **parameters),
            }
            return session.store(name, None, plain(features))
        if name == "double_top":
            module = runtime.load("f_ダブルトップ")
            policy = policy_from(module, parameters)
            candidate = module.detect_candidate(context, policy)
            return session.store(name, (candidate, policy),
                                 {"candidate": plain(candidate)}, status="ok" if candidate else "no_signal")
        if name == "resistance_breakout":
            module = runtime.load("fResistanceBreakoutAnalysis")
            policy = policy_from(module, parameters)
            arguments = []

            def collect(**kwargs):
                arguments.append(kwargs)
                return None

            with runtime.binding(module, "build_order", collect):
                module.build_orders_for_decision(candles, mode=session.request.mode, policy=policy)
            features = {"signals": [plain({key: value for key, value in item.items()
                                          if key not in {"line_class", "context", "candle_analysis_class"}})
                                    for item in arguments]}
            return session.store(name, arguments, features, status="ok" if arguments else "no_signal")
        if parameters:
            raise ValueError("flip uses the original approved policy and artifact")
        if runtime.artifact_directory is None:
            raise AnalysisNotReady("flip requires an explicitly configured artifact directory")
        module = runtime.load("fFlipPredictLive")
        try:
            policy = module.bind_policy(session.request.pair)
        except FileNotFoundError as error:
            raise AnalysisNotReady("approved flip artifact is unavailable") from error
        signal = module.build_signal_from_candle_analysis(
            candles, jst_time(session.request.decision_time).tz_convert("UTC").to_pydatetime())
        return session.store(name, (signal, policy), {"signal": plain(signal)},
                             status="ok" if signal else "no_signal")
