"""Offline contracts for the unchanged-source analysis adapter."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import hashlib
import io
import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd
import pytest

from ogami_oanda.adapters.legacy.main_analysis.analysis import analyze
from ogami_oanda.adapters.legacy.main_analysis.backend import MainSourceAnalysis
from ogami_oanda.adapters.legacy.main_analysis.inputs import peak_objects
from ogami_oanda.adapters.legacy.main_analysis.loader import SourceRuntime
from ogami_oanda.adapters.legacy.main_analysis.orders import build_order_candidates, from_native_order
from ogami_oanda.adapters.legacy.main_analysis.source import SOURCE_MODULES
from ogami_oanda.domain.analysis.main_contracts import (
    AnalysisIntegrityError, AnalysisNotReady, UnsupportedAnalysisDependency,
)
from ogami_oanda.domain.analysis.main_orders import to_order_intents
from ogami_oanda.application.services.order_planner import OrderPlanner
from ogami_oanda.domain.orders.models import OrderContext

from tests.fakes.main_analysis import request_for

PAIRS = ("USD_JPY", "EUR_USD", "AUD_USD")




@pytest.fixture(scope="module")
def backend(main_source_directory):
    return MainSourceAnalysis(source_directory=main_source_directory)


def test_direct_sources_are_original_bytes_without_settings(backend):
    for name, data in backend.sources.contents.items():
        assert (backend.source_directory / f"{name}.py").read_bytes() == data
    assert not {"tokens", "send_notice", "fAnalysis_order_Main", "fFlipWatch"} & backend.sources.contents.keys()


def test_all_native_imports_leave_host_namespace_and_stdout_unchanged(backend):
    before = {name: sys.modules.get(name) for name in SOURCE_MODULES | {"tokens", "send_notice"}}
    path, output, import_function = list(sys.path), sys.stdout, __import__
    with SourceRuntime(sources=backend.sources) as runtime:
        prefix = runtime.prefix
        for name in sorted(SOURCE_MODULES):
            runtime.load(name)
        assert len(runtime.modules) == len(SOURCE_MODULES)
        contextlib = runtime._shim("contextlib")
        capture = io.StringIO()
        with contextlib.redirect_stdout(capture):
            runtime.load("fGeneric").print_json({"isolated": True})
            assert sys.stdout is output
        assert "isolated" in capture.getvalue()
        with pytest.raises(UnsupportedAnalysisDependency):
            runtime._shim("requests").get("unused")
        with pytest.raises(UnsupportedAnalysisDependency):
            runtime._shim("tokens").access_token
    assert not any(name.startswith(prefix) for name in sys.modules)
    assert list(sys.path) == path
    assert __import__ is import_function
    assert all(sys.modules.get(name) is value for name, value in before.items())


def test_parallel_runtimes_have_independent_pairs_and_dataclasses(backend):
    def check(pair):
        with SourceRuntime(sources=backend.sources) as runtime:
            generic = runtime.load("fGeneric")
            generic.set_current_pair(pair)
            core = runtime.load("fDoubleTopCore")
            return generic.currentPair.name, core.DoubleTopPolicyV1, runtime.prefix
    with ThreadPoolExecutor(max_workers=3) as executor:
        results = list(executor.map(check, PAIRS))
    assert [value[0] for value in results] == list(PAIRS)
    assert len({value[1] for value in results}) == 3
    assert all(not any(name.startswith(value[2]) for name in sys.modules) for value in results)


@pytest.mark.parametrize("pair", PAIRS)
def test_native_line_and_bridge_orders_match(pair, backend):
    request = request_for(pair)
    with backend.evaluation(request) as session:
        result = analyze(session, "line")
        actual = build_order_candidates(session, result)
        assert build_order_candidates(session, result) is actual
    with backend.evaluation(request) as reference:
        source = reference.runtime.load("fLineAnalysis")
        source.LineOrderCoordinator._inspection_usd_jpy_close = pd.Series(dtype=float)
        native = source.MainAnalysis(reference.candles, mode=request.mode)
        expected = tuple(from_native_order(order, "line") for order in native.exe_order_classes)
    assert actual == expected


@pytest.mark.parametrize("pair", PAIRS)
def test_breakout_matches_original_and_detaches_orders(pair, backend):
    request = request_for(pair)
    with backend.evaluation(request) as session:
        result = analyze(session, "resistance_breakout")
        actual = build_order_candidates(session, result)
        source = session.runtime.load("fResistanceBreakoutAnalysis")
        expected = tuple(from_native_order(order, "resistance_breakout")
                         for order in source.build_orders_for_decision(session.candles))
        assert actual == expected
        assert actual, "synthetic peak should exercise positive candidate generation"
    for candidate in actual:
        # Checkpoint metadata must no longer hold private strategy objects.
        json.dumps(dict(candidate.metadata), allow_nan=False)


@pytest.mark.parametrize("name", ["candles", "shape", "stair", "double_top"])
def test_analysis_only_entries_return_usable_results(name, backend):
    with backend.evaluation(request_for()) as session:
        result = analyze(session, name)
        assert result.analysis == name
        assert result.features
        assert build_order_candidates(session, result) == ()


def test_completed_frames_and_future_input_independence(backend):
    request = request_for()
    before = {key: value.copy(deep=True) for key, value in request.candle_frames.items()}
    with backend.evaluation(request) as session:
        analyze(session, "candles")
        original_peaks = {key: value.peaks_original for key, value in peak_objects(session.candles).items()}
        assert session.candles.m5_completed_df_r.iloc[0]["time_jp"] == "2026/09/11 11:55:00"
        assert session.candles.h1_completed_df_r.iloc[0]["time_jp"] == "2026/09/11 11:00:00"
    future = {}
    for name, frame in before.items():
        row = frame.iloc[[0]].copy()
        row["time_jp"] = "2026/09/12 00:00:00"
        row[["open", "close", "high", "low"]] = 500
        future[name] = pd.concat([row, frame], ignore_index=True)
    with backend.evaluation(replace(request, candle_frames=future)) as session:
        analyze(session, "candles")
        for key, value in peak_objects(session.candles).items():
            assert value.peaks_original == original_peaks[key]
    for name, frame in request.candle_frames.items():
        pd.testing.assert_frame_equal(frame, before[name])


def test_all_completed_history_keeps_latest_completed_candle(backend):
    request = request_for()
    completed = {key: frame.iloc[1:].copy() for key, frame in request.candle_frames.items()}
    with backend.evaluation(replace(request, candle_frames=completed)) as session:
        analyze(session, "candles")
        assert session.candles.m5_completed_df_r.iloc[0]["time_jp"] == completed["M5"].iloc[0]["time_jp"]
        assert session.candles.h1_completed_df_r.iloc[0]["time_jp"] == completed["H1"].iloc[0]["time_jp"]


@pytest.mark.parametrize("fault", ["duplicate", "nonfinite", "flags", "missing_flags"])
def test_bad_history_is_not_no_signal(fault, backend):
    request = request_for(mode="live")
    frames = {key: value.copy() for key, value in request.candle_frames.items()}
    if fault == "duplicate":
        frames["M5"] = pd.concat([frames["M5"], frames["M5"].iloc[[1]]], ignore_index=True)
    elif fault == "nonfinite":
        frames["M5"].loc[1, "close"] = np.nan
    elif fault == "flags":
        frames["M5"]["is_complete"] = False
    else:
        frames["M5"] = frames["M5"].drop(columns="complete")
    with backend.evaluation(replace(request, candle_frames=frames)) as session:
        with pytest.raises(AnalysisIntegrityError):
            analyze(session, "line")


def test_empty_history_and_missing_flip_artifact_are_not_ready(backend):
    request = request_for()
    with backend.evaluation(replace(request, candle_frames={})) as session:
        with pytest.raises(AnalysisNotReady):
            analyze(session, "line")
    with backend.evaluation(request) as session:
        with pytest.raises(AnalysisNotReady, match="artifact"):
            analyze(session, "flip")


def test_cross_session_and_closed_result_rejected(backend):
    with backend.evaluation(request_for()) as first, backend.evaluation(request_for()) as second:
        result = analyze(first, "shape")
        with pytest.raises(AnalysisIntegrityError, match="another evaluation"):
            build_order_candidates(second, result)
    with pytest.raises(RuntimeError, match="closed"):
        build_order_candidates(first, result)


@pytest.mark.parametrize("pair", PAIRS)
@pytest.mark.parametrize("order_type,direction", [("MARKET", 1), ("LIMIT", -1), ("STOP", 1)])
def test_resolved_native_order_prices_and_units_survive_conversion(pair, order_type, direction, backend):
    request = request_for(pair)
    with backend.evaluation(request) as session:
        candles = session.candles
        generic = session.runtime.load("fGeneric")
        pair_info = generic.currency_pair(pair)
        entry = request.current_price + pair_info.pips_to_price(3)
        order = session.runtime.load("classOrderCreate").Order({
            "name": "bridge-contract", "pair": pair, "current_price": request.current_price,
            "target": entry, "direction": direction, "type": order_type,
            "tp": pair_info.pips_to_price(12), "lc": pair_info.pips_to_price(8),
            "risk_yen": 500, "usd_jpy_rate": 150, "priority": 5, "lc_change": [],
            "decision_time": "2026/09/11 12:00:00", "order_timeout_min": 10,
            "trade_timeout_min": 30, "candle_analysis_class": candles,
        })
        candidate = from_native_order(order, "line")
        intent, = to_order_intents((candidate,))
        plan = OrderPlanner().plan(intent, OrderContext(order.target_price + pair_info.pips_to_price(7), order.decision_time))
        assert (plan.target_price, plan.take_profit_price, plan.stop_loss_price, intent.units) == (
            order.target_price, order.tp_price, order.lc_price, order.units)
        assert plan.broker_request.units == order.units * direction
        for execution in ("waiting", "trial", "unsupported"):
            assert not to_order_intents((replace(candidate, execution=execution),))


def test_original_modules_are_not_imported_directly_by_production_code():
    root = Path(__file__).parents[1] / "src" / "ogami_oanda"
    import ast
    for path in root.rglob("*.py"):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            else:
                continue
            assert not any(".upstream" in name or name.split(".")[0] in SOURCE_MODULES for name in names), path


def test_backend_can_evaluate_after_exception_without_state_leak(backend):
    with backend.evaluation(request_for()) as session:
        prefix = session.runtime.prefix
        with pytest.raises(UnsupportedAnalysisDependency):
            analyze(session, "fFlagInspection")
    assert not any(name.startswith(prefix) for name in sys.modules)
    first, second = backend.evaluate(request_for()), backend.evaluate(request_for())
    assert first.candidates == second.candidates


@pytest.mark.parametrize("pair", PAIRS)
def test_double_top_positive_signal_and_trial_match_original(pair, backend):
    request = request_for(pair)
    frame = request.candle_frames["M5"]
    pip = .01 if pair == "USD_JPY" else .0001
    base = {"USD_JPY": 150, "EUR_USD": 1.1, "AUD_USD": .7}[pair]
    pattern = [0, 5, 10, 15, 20, 15, 10, 5, 0, 5, 10, 15, 20, 15, 10, 5, 0, -5, -5]
    for index, offset in enumerate(reversed(pattern)):
        close = base + offset * pip
        frame.loc[index, ["close", "open", "high", "low"]] = [close, close-2*pip, close+4*pip, close-6*pip]
    request = replace(request, current_price=float(frame.iloc[0]["close"]))
    with backend.evaluation(request) as session:
        result = analyze(session, "double_top")
        actual, = build_order_candidates(session, result)
        module = session.runtime.load("f_ダブルトップ")
        context = session.candles.require_basic_analysis()
        native = module.detect_candidate(context)
        assert native is not None
        expected = from_native_order(module.build_order(native, context, session.candles, request.mode), "double_top")
        assert actual == expected
        assert actual.execution == "trial"
        assert to_order_intents((actual,)) == ()


def _fixture_flip_policy(session):
    """Authorize synthetic policy bytes inside this test's private namespace only."""
    policy = session.runtime.load("fFlipPredictPolicy")
    core = session.runtime.load("count2_flip_core")
    pair = session.request.pair
    artifact = {
        "version": policy.POLICY_VERSION, "pair": pair,
        "top_condition_policy": {"minimum_matched_conditions": 1},
        "selected_top_conditions": [core.RankedPolicyCondition(
            1, core.TIER_HIGH, core.PolicyCondition("fixture", "fixture")).to_dict()],
        "tier_execution_configs": [config.to_dict() for config in core.default_tier_execution_configs()],
        "top_condition_limit": 1, "execution": {"watch_entry": core.FlipWatchEntryConfig().to_dict()},
    }
    data = json.dumps(artifact).encode()
    path = policy.artifact_path(pair)
    path.write_bytes(data)
    policy.APPROVED_PAIRS[pair]["artifact_sha256"] = hashlib.sha256(data).hexdigest()
    return policy, path


@pytest.mark.parametrize("pair", PAIRS)
def test_flip_analysis_artifact_integrity_and_waiting_order(pair, tmp_path, main_source_directory):
    from ogami_oanda.adapters.legacy.main_analysis.inputs import jst_time
    from ogami_oanda.adapters.legacy.main_analysis.values import plain
    request = request_for(pair)
    with MainSourceAnalysis(source_directory=main_source_directory, artifact_directory=tmp_path).evaluation(request) as session:
        policy, path = _fixture_flip_policy(session)
        result = analyze(session, "flip")
        live = session.runtime.load("fFlipPredictLive")
        decision = jst_time(request.decision_time).tz_convert("UTC").to_pydatetime()
        assert result.features["signal"] == plain(live.build_signal_from_candle_analysis(session.candles, decision))
        # Exercise the candidate entry point with the native signal schema even
        # when these raw candles legitimately do not trigger a flip signal.
        core = session.runtime.load("count2_flip_core")
        signal = {"tp_pips": 12, "lc_pips": 8, "line_price": request.current_price,
                  "order_direction": 1, "signal_tier": core.TIER_HIGH, "highest_matched_rank": 1,
                  "decision_time_utc": decision.isoformat(), "peak_direction": -1,
                  "a_range_pips": 10, "signal_id": "fixture-signal"}
        result = session.store("flip", (signal, live.ACTIVE_POLICY), {"signal": signal})
        candidate, = build_order_candidates(session, result)
        native = session.runtime.load("fFlipOrder").build_order(
            signal, pair, session.candles, live.ACTIVE_POLICY, session.candles.base_oa)
        assert candidate == from_native_order(native, "flip")
        assert candidate.execution == "waiting"
        assert candidate.metadata["flip_watch_config"]
        assert not to_order_intents((candidate,))
        path.write_bytes(path.read_bytes() + b" ")
        with pytest.raises(AnalysisIntegrityError, match="approved policy"):
            analyze(session, "flip")
        assert policy.APPROVED_PAIRS[pair]["artifact_sha256"] != hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.mark.parametrize("decision,m30,h1", [
    ("2026-09-11 12:00:00", "2026/09/11 11:30:00", "2026/09/11 11:00:00"),
    ("2026-09-11 12:30:00", "2026/09/11 12:00:00", "2026/09/11 11:00:00"),
])
def test_native_timeframe_boundaries_and_m30_fallback(decision, m30, h1, backend):
    request = request_for(latest=decision)
    with backend.evaluation(request) as session:
        result = analyze(session, "candles")
        assert result.features["M30"]["completed_frame"].iloc[0]["time_jp"] == m30
        assert result.features["H1"]["completed_frame"].iloc[0]["time_jp"] == h1
    frames = {key: frame for key, frame in request.candle_frames.items() if key != "M30"}
    with backend.evaluation(replace(request, candle_frames=frames)) as session:
        bundle = session.candles.get_timeframe_bundle("M30")
        assert bundle.source_granularity == "H1"
        assert bundle.completed_df_r.iloc[0]["time_jp"] == h1


def test_concurrent_evaluations_match_sequential_results(backend):
    requests = [replace(request_for(pair), risk_yen=500, usd_jpy_rate=149) for pair in PAIRS]
    sequential = [backend.evaluate(request).candidates for request in requests]
    with ThreadPoolExecutor(max_workers=3) as executor:
        parallel = list(executor.map(backend.evaluate, requests))
    assert [item.candidates for item in parallel] == sequential
    assert all(item.diagnostics["source_directory"] == str(backend.source_directory) for item in parallel)
    assert not any(name.startswith("_ogami_main_") for name in sys.modules)


def test_source_rates_and_clock_are_supplied_not_fetched(backend):
    from ogami_oanda.adapters.legacy.main_analysis.inputs import line_view
    request = replace(request_for("EUR_USD", mode="live"), usd_jpy_rate=143.25,
                      evaluation_time="2026-09-11 12:00:09")
    with backend.evaluation(request) as session:
        view = line_view(session.runtime, request, session.candles)
        assert view.line_order_coordinator()._get_usd_jpy_rate(session.candles.decision_time) == 143.25
        now = session.runtime._shim("datetime").datetime.now()
        assert now.isoformat() == "2026-09-11T12:00:09"
        assert session.candles.decision_time == pd.Timestamp("2026-09-11 12:00:00")
    rates = pd.DataFrame({"time_jp": ["2026/09/11 11:00:00", "2026/09/12 12:00:00"], "close": [142.0, 999.0]})
    with backend.evaluation(replace(request, mode="inspection", conversion_candles=rates)) as session:
        view = line_view(session.runtime, session.request, session.candles)
        assert view.line_order_coordinator()._get_usd_jpy_rate(session.candles.decision_time) == 142.0


def test_strategy_uses_injected_calculation_once_and_returns_completed_protection(backend):
    from ogami_oanda.strategy.original.strategy import OriginalStrategy
    from ogami_oanda.strategy.shared.contracts import StrategyInput, StrategyQuote
    request = request_for()
    def forbidden(*args, **kwargs):
        raise AssertionError("old candidate computation ran on the injected path")
    strategy = OriginalStrategy(candidate_builder=forbidden, candidate_context_builder=forbidden, analysis_backend=backend)
    decision = strategy.decide(StrategyInput(
        StrategyQuote(request.pair, request.current_price, request.current_price, request.current_price),
        candle_frames=request.candle_frames, decision_time=request.decision_time,
        evaluation_time=pd.Timestamp("2026-09-11 12:00:09"),
    ))
    assert decision.candle_protection.previous_candle["time_jp"] == "2026/09/11 11:55:00"
    assert decision.diagnostics["main_analysis"]["source_directory"] == str(backend.source_directory)
    json.dumps(decision.diagnostics, allow_nan=False)


def test_composition_keeps_explicit_builders_and_backend(backend):
    from ogami_oanda.entrypoints.main_analysis import bind_main_analysis
    from ogami_oanda.strategy.original.strategy import OriginalStrategy
    custom = OriginalStrategy(candidate_builder=lambda *args: [])
    assert bind_main_analysis(custom, mode="live") is None
    assert custom.analysis.analysis_backend is None
    supplied = OriginalStrategy(analysis_backend=backend)
    assert bind_main_analysis(supplied, mode="live") is backend
    assert supplied.analysis.analysis_mode == "live"
    assert bind_main_analysis(supplied, mode="inspection") is backend
    assert supplied.analysis.analysis_mode == "inspection"
