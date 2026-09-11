"""Create candidates with upstream order functions, without submitting orders."""

from __future__ import annotations

from dataclasses import replace
from math import isfinite

from ogami_oanda.domain.analysis.main_contracts import AnalysisIntegrityError, OrderCandidate, UnsupportedAnalysisDependency

from .values import plain


def from_native_order(order, analysis):
    """Copy finalized prices, units and management metadata without recalculation."""
    required = {"order_json", "exe_order_plan", "instrument", "direction", "ls_type", "target_price", "tp_price",
                "lc_price", "units", "name", "priority", "order_timeout_min", "trade_timeout_min",
                "decision_time", "lc_change"}
    missing = sorted(name for name in required if not hasattr(order, name))
    if missing:
        raise UnsupportedAnalysisDependency(f"unsupported upstream order schema; missing: {', '.join(missing)}")
    plan = {**plain(order.order_json), **plain(order.exe_order_plan)}
    execution = str(plan.get("execution_mode") or "ready")
    if execution not in {"ready", "execute", "trial"}:
        execution = "unsupported"
    if execution == "execute":
        execution = "ready"
    if analysis == "double_top":
        execution = "trial"
    if not bool(plan.get("order_permission", True)):
        execution = "trial" if execution == "trial" else "waiting"
    if execution == "ready" and (plan.get("allow_followup_order") is False or plan.get("profit_lock_ratio") is not None
            or plan.get("line_order_mode") == "predict_reversal" or plan.get("owner_tag")):
        execution = "unsupported"
    candidate = OrderCandidate(
        pair=str(plan.get("pair", order.instrument)),
        direction=int(order.direction), order_type=str(order.ls_type),
        target_price=float(order.target_price), take_profit_price=float(order.tp_price),
        stop_loss_price=float(order.lc_price), units=int(order.units), name=str(order.name),
        priority=int(order.priority), order_timeout_min=int(order.order_timeout_min),
        trade_timeout_min=int(order.trade_timeout_min), decision_time=str(order.decision_time),
        lc_change=tuple(plain(order.lc_change or [])), execution=execution,
        metadata={**plan, "source": plan.get("source") or analysis, "main_analysis": analysis},
    )
    if candidate.direction not in (-1, 1) or candidate.units <= 0:
        raise AnalysisIntegrityError("upstream order has invalid direction or units")
    if not all(isfinite(value) and value > 0 for value in (
        candidate.target_price, candidate.take_profit_price, candidate.stop_loss_price
    )):
        raise AnalysisIntegrityError("upstream order has invalid resolved prices")
    return candidate


def build_order_candidates(session, result, parameters=None):
    """Build native orders once from a result owned by this open session."""
    native = session.native(result)
    parameters = dict(parameters or {})
    if result.result_id in session.completed_orders:
        saved_parameters, orders = session.completed_orders[result.result_id]
        if saved_parameters != parameters:
            raise AnalysisIntegrityError("order settings changed within one evaluation")
        return orders
    with session.translated_errors():
        runtime = session.runtime
        candles = session.candles
        orders = []
        if result.analysis == "line":
            if parameters.keys() - {"risk_yen"}:
                raise ValueError("line order settings support risk_yen only")
            source = runtime.load("fLineAnalysis")
            if "risk_yen" in parameters:
                risk = float(parameters["risk_yen"])
                if not isfinite(risk) or risk <= 0:
                    raise ValueError("risk_yen must be positive and finite")
                source.gl_risk_yen = source.gl_live_usd_jpy_risk_yen = risk
            original_calculator = source.LineStrengthCal

            def prepared_lines(candle_analysis, foot, time_before_foot_count=30, **kwargs):
                key = (str(foot).lower(), time_before_foot_count)
                if candle_analysis is candles and not kwargs and key in native["lines"]:
                    return native["lines"][key]
                return original_calculator(candle_analysis, foot, time_before_foot_count, **kwargs)

            # Reuse the prepared lines while retaining native RSI gates, candidate
            # selection, immediate/future precedence, sizing and session policies.
            with runtime.binding(source, "LineStrengthCal", prepared_lines):
                native["view"].line_analysis()
            orders = native["view"].exe_order_classes
        elif result.analysis == "double_top":
            allowed = {"target_height_multiplier", "stop_buffer_pips", "min_order_distance_pips",
                       "risk_yen", "priority", "trade_timeout_min"}
            if parameters.keys() - allowed:
                raise ValueError("double_top order settings cannot change detection conditions")
            candidate, policy = native
            if candidate is not None:
                module = runtime.load("f_ダブルトップ")
                policy = replace(policy, **parameters) if parameters else policy
                order = module.build_order(candidate, candles.require_basic_analysis(), candles,
                                           session.request.mode, policy)
                orders = [order] if order is not None else []
        elif result.analysis == "resistance_breakout":
            if parameters:
                raise ValueError("breakout policy is fixed by its analysis result")
            module = runtime.load("fResistanceBreakoutAnalysis")
            orders = [module.build_order(**arguments) for arguments in native]
        elif result.analysis == "flip":
            if parameters:
                raise ValueError("flip order policy comes from the approved artifact")
            signal, policy = native
            if signal is not None:
                module = runtime.load("fFlipOrder")
                orders = [module.build_order(signal, session.request.pair, candles, policy, candles.base_oa)]
        elif parameters:
            raise ValueError("this analysis does not create orders")
        order_values = []
        for order in orders:
            plan = getattr(order, "exe_order_plan", {})
            if plan.get("source") == "line_control":
                session.control_events.append(plain(plan))
                continue
            order_values.append(from_native_order(order, result.analysis))
        candidates = tuple(order_values)
        session.completed_orders[result.result_id] = (parameters, candidates)
        return candidates
