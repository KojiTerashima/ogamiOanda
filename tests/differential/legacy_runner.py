from __future__ import annotations

import contextlib
import csv
import importlib
import io
import json
import os
import socket
import sys
import tempfile
import types
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

from .analysis_trace import (
    builtin_value,
    candidates_store_summary,
    frame_store_summary,
    legacy_intent_summary,
    line_store_summary,
    peaks_store_summary,
    plan_summary,
    strategy_profiles_summary,
)
from .frame_factory import build_frame_store, build_response_store
from .scenario import DifferentialScenario


@dataclass(frozen=True)
class LegacyRunnerResult:
    trace: dict[str, Any]
    log: str


class LegacyRunnerError(RuntimeError):
    pass


def run_legacy_scenario(scenario: DifferentialScenario) -> LegacyRunnerResult:
    with _legacy_sandbox(scenario) as sandbox:
        output = io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            if scenario.kind == "analysis_order":
                trace = _run_analysis_order(scenario)
            elif scenario.kind == "order_payload":
                trace = _run_order_payload(scenario)
            elif scenario.kind == "position_lifecycle":
                trace = _run_position_lifecycle(scenario)
            elif scenario.kind == "live_schedule":
                trace = _run_live_schedule(scenario)
            else:
                raise LegacyRunnerError(f"Unsupported scenario kind: {scenario.kind}")
        sandbox.assert_no_network_calls()
        return LegacyRunnerResult(trace=trace, log=output.getvalue())


def _run_analysis_order(scenario: DifferentialScenario) -> dict[str, Any]:
    classOanda = importlib.import_module("classOanda")
    classCandleAnalysis = importlib.import_module("classCandleAnalysis")
    fLineAnalysis = importlib.import_module("fLineAnalysis")
    fAnalysis_order_Main = importlib.import_module("fAnalysis_order_Main")
    fGeneric = importlib.import_module("fGeneric")
    _assert_module_paths(
        {
            "classOanda": classOanda,
            "classCandleAnalysis": classCandleAnalysis,
            "fLineAnalysis": fLineAnalysis,
            "fAnalysis_order_Main": fAnalysis_order_Main,
            "fGeneric": fGeneric,
        }
    )

    raw_responses = build_response_store(scenario.pair, scenario.payload["frames"])
    raw_frames = {
        timeframe: classOanda.pd.DataFrame(response["candles"])
        for timeframe, response in raw_responses.items()
    }
    pair_info = fGeneric.currency_pair(scenario.pair)
    frames = {}
    for timeframe, raw_frame in raw_frames.items():
        prepared = raw_frame.copy()
        prepared.insert(
            0,
            "time_jp",
            prepared.apply(lambda row: classOanda.iso_to_jstdt(row, "time"), axis=1),
        )
        prepared = prepared.sort_values("time_jp", ascending=True).reset_index(drop=True)
        prepared = classOanda.add_basic_data(prepared, pair_info)
        prepared = classOanda.add_rsi(prepared)
        if timeframe != "S5":
            prepared = classOanda.add_bb_data(prepared, pair_info)
        frames[timeframe] = prepared.sort_values(
            "time_jp",
            ascending=False,
        ).reset_index(drop=True)
    current_price = float(scenario.payload["current_price"])

    candle = classCandleAnalysis.candleAnalysis(
        None,
        scenario.pair,
        0,
        m5_df_r=frames["M5"].copy(),
        h1_df_r=frames["H1"].copy(),
        m30_df_r=frames["M30"].copy(),
        s5_df_r=frames["S5"].copy(),
        current_price=current_price,
    )

    analysis_cls = getattr(fLineAnalysis, "_LegacyMainAnalysis", None)
    if analysis_cls is None:
        analysis_cls = getattr(fLineAnalysis, "MainAnalysis", None)
    if analysis_cls is None:
        raise LegacyRunnerError("fLineAnalysis analysis class not found")

    analysis = analysis_cls(candle, None, "inspection")
    profile = analysis.each_pair_line_strategy_profile
    line_class_m5_l = fLineAnalysis.LineStrengthCal(candle, "m5", 60)
    line_class_m5_s = fLineAnalysis.LineStrengthCal(candle, "m5", 30)
    rsi_info = {
        "rsi_1": analysis.df_r_m5.iloc[0].get("RSI"),
        "rsi_2": analysis.df_r_m5.iloc[1].get("RSI"),
        "rsi_3": analysis.df_r_m5.iloc[2].get("RSI"),
    }
    line_context = profile.calculate_line_strength(
        analysis,
        line_class_m5_l,
        line_class_m5_s,
        analysis.line_class_h1_l,
        analysis.line_class_h1_s,
        analysis.current_price,
        analysis.df_r_m5.iloc[0]["time_jp"],
        rsi_info,
    )
    grouped = profile.group_lines(line_context)

    coordinator = grouped["coordinator"]
    selected_immediate = coordinator.select_line_candidates(
        grouped["immediate_candidates"],
        grouped["rsi_info"],
        grouped["decision_time"],
        "immediate",
        profile.immediate_recommended_reasons,
    )
    selected_future_resist = coordinator.select_line_candidates(
        grouped["future_resist_candidates"],
        grouped["rsi_info"],
        grouped["decision_time"],
        "future_resist",
        profile.future_resist_recommended_reasons,
    )
    selected_future_break = coordinator.select_line_candidates(
        grouped["future_break_candidates"],
        grouped["rsi_info"],
        grouped["decision_time"],
        "future_break",
        profile.future_break_recommended_reasons,
    )

    wrapped = fAnalysis_order_Main.wrap_all_analysis(candle, None, "inspection")
    legacy_order_plans = [dict(order.exe_order_plan) for order in wrapped.exe_order_classes]
    frame_map = {
        "M5": candle.d5_df_r,
        "H1": candle.h1_df_r,
        "M30": candle.d30_df_r,
        "S5": candle.s5_df_r,
    }
    peaks_map = {
        "M5": candle.peaks_class,
        "H1": candle.peaks_class_hour,
        "M30": candle.peaks_class_m30,
    }
    selected_by_mode = {
        "immediate": selected_immediate,
        "future_resist": selected_future_resist,
        "future_break": selected_future_break,
    }
    enriched_by_mode = {
        "immediate": [],
        "future_resist": [],
        "future_break": [],
    }
    raw_by_mode = {
        "immediate": grouped["immediate_candidates"],
        "future_resist": grouped["future_resist_candidates"],
        "future_break": grouped["future_break_candidates"],
    }
    for plan in legacy_order_plans:
        mode = _legacy_plan_candidate_mode(plan)
        candidate = _match_legacy_plan_candidate(
            plan,
            [*selected_by_mode[mode], *raw_by_mode[mode]],
        )
        if candidate is not None:
            enriched_by_mode[mode].append((candidate, plan))

    return {
        "pair": scenario.pair,
        "kind": scenario.kind,
        "scenario_id": scenario.scenario_id,
        "events": [
            {
                "kind": "analysis",
                "decision_time": analysis.df_r_m5.iloc[0]["time_jp"],
                "current_price": current_price,
                "raw_candidate_counts": {
                    "immediate": len(grouped["immediate_candidates"]),
                    "future_resist": len(grouped["future_resist_candidates"]),
                    "future_break": len(grouped["future_break_candidates"]),
                },
                "selected_candidate_counts": {
                    "immediate": len(selected_immediate),
                    "future_resist": len(selected_future_resist),
                    "future_break": len(selected_future_break),
                },
                "frames": frame_store_summary(frame_map),
                "peaks": peaks_store_summary(peaks_map),
                "lines": line_store_summary(line_context),
                "candidates": candidates_store_summary(
                    {
                        "immediate": grouped["immediate_candidates"],
                        "future_resist": grouped["future_resist_candidates"],
                        "future_break": grouped["future_break_candidates"],
                    },
                    selected_by_mode,
                    enriched_by_mode,
                ),
                "strategy_profiles": strategy_profiles_summary(
                    {
                        "immediate": grouped["immediate_candidates"],
                        "future_resist": grouped["future_resist_candidates"],
                        "future_break": grouped["future_break_candidates"],
                    }
                ),
                "intents": [legacy_intent_summary(plan) for plan in legacy_order_plans],
                "intent_metadata_loss": [{} for plan in legacy_order_plans],
                "plans": [plan_summary(plan) for plan in legacy_order_plans],
                "adapter_plans": [
                    plan_summary(plan) for plan in legacy_order_plans
                ],
                "payloads": [
                    dict((plan.get("for_api_json") or {}).get("order", {}))
                    for plan in legacy_order_plans
                ],
                "legacy_plans": [
                    _legacy_plan_summary(plan) for plan in legacy_order_plans
                ],
            }
        ],
    }


def _legacy_plan_candidate_mode(plan: Mapping[str, Any]) -> str:
    if str(plan.get("type", "")).upper() == "MARKET":
        return "immediate"
    if str(plan.get("line_entry_type", "")).lower() == "reversal":
        return "future_resist"
    return "future_break"


def _match_legacy_plan_candidate(
    plan: Mapping[str, Any],
    candidates: list[dict[str, Any]],
) -> dict[str, Any] | None:
    plan_strategy = plan.get("line_strategy")
    plan_direction = plan.get("direction")
    plan_line_price = plan.get("line_price")
    for candidate in candidates:
        if candidate.get("line_strategy") != plan_strategy:
            continue
        if int(candidate.get("direction", 0)) != int(plan_direction or 0):
            continue
        candidate_price = candidate.get("line_price")
        if plan_line_price is None or candidate_price is None:
            continue
        if abs(float(candidate_price) - float(plan_line_price)) <= 1e-12:
            return candidate
    return None


def _run_order_payload(scenario: DifferentialScenario) -> dict[str, Any]:
    classOrderCreate = importlib.import_module("classOrderCreate")
    _assert_module_paths({"classOrderCreate": classOrderCreate})
    order_input = dict(scenario.payload["order_input"])
    order_input.setdefault("pair", scenario.pair)
    if "candle_analysis_class" not in order_input:
        order_input["candle_analysis_class"] = _LegacyCandleAnalysisStub()
    order = classOrderCreate.Order(order_input)

    return {
        "pair": scenario.pair,
        "kind": scenario.kind,
        "scenario_id": scenario.scenario_id,
        "events": [
            {
                "kind": "order_payload",
                "plan": _legacy_plan_summary(dict(order.exe_order_plan)),
                "payload": dict(order.data.get("order", {})),
            }
        ],
    }


def _run_position_lifecycle(scenario: DifferentialScenario) -> dict[str, Any]:
    position_case = scenario.payload["position"].get("case")
    if position_case == "watching":
        return _run_position_watching(scenario)
    if position_case == "pending_timeout":
        return _run_position_pending_timeout(scenario)
    if position_case == "lc_change":
        return _run_position_lc_change(scenario)
    if position_case == "portfolio_acceptance":
        return _run_portfolio_acceptance(scenario)
    if position_case == "broker_outcome":
        return _run_broker_outcome(scenario)
    if position_case == "linkage_hedge":
        return _run_linkage_hedge(scenario)
    if position_case == "close_reporting":
        return _run_close_reporting(scenario)
    if position_case == "trade_timeout_disabled":
        return _run_trade_timeout_disabled(scenario)
    if position_case == "candle_lc":
        return _run_candle_lc(scenario)
    if position_case == "restore":
        return _run_restore(scenario)
    if position_case == "active_dedup":
        return _run_active_dedup(scenario)

    classPositionControl = importlib.import_module("classPositionControl")
    _assert_module_paths({"classPositionControl": classPositionControl})

    controller = classPositionControl.position_control(False, scenario.pair)
    registration_result = None

    order_specs = scenario.payload["position"].get("orders", [])
    if order_specs:
        classOrderCreate = importlib.import_module("classOrderCreate")
        _assert_module_paths({"classOrderCreate": classOrderCreate})
        orders = [classOrderCreate.Order(dict(spec)) for spec in order_specs]
        registration_result = controller.order_class_add(orders)

    summary = controller.position_check()
    life = controller.life_check()

    return {
        "pair": scenario.pair,
        "kind": scenario.kind,
        "scenario_id": scenario.scenario_id,
        "events": [
            {
                "kind": "position_lifecycle",
                "registration": {
                    "accepted_count": 0,
                    "rejected_count": 0,
                    "raw_result": registration_result,
                },
                "counts": {
                    "watching": len(summary.get("watching_list", [])),
                    "pending": len(summary.get("pending_positions", [])),
                    "open": len(summary.get("open_positions", [])),
                    "life_exist": bool(life.get("life_exist", False)),
                },
            },
        ],
    }


def _run_position_watching(scenario: DifferentialScenario) -> dict[str, Any]:
    classOrderCreate = importlib.import_module("classOrderCreate")
    classPosition = importlib.import_module("classPosition")
    _assert_module_paths(
        {
            "classOrderCreate": classOrderCreate,
            "classPosition": classPosition,
        }
    )
    position_spec = scenario.payload["position"]
    raw_order = dict(position_spec["order"])
    raw_order.setdefault("pair", scenario.pair)
    raw_order.setdefault("decision_time", scenario.payload["decision_time"])
    raw_order.setdefault("order_permission", False)
    raw_order.setdefault(
        "candle_analysis_class",
        _LegacyCandleAnalysisStub(float(raw_order["current_price"])),
    )

    first_at = datetime.fromisoformat(str(position_spec["ticks"][0]["at"]))

    class _FrozenDateTime(datetime):
        current = first_at

        @classmethod
        def now(cls, tz=None):
            if tz is None:
                return cls.current
            return tz.fromutc(cls.current.replace(tzinfo=tz))

    original_datetime = classPosition.datetime.datetime
    classPosition.datetime.datetime = _FrozenDateTime
    try:
        order = classOrderCreate.Order(raw_order)
        position = classPosition.order_information(
            str(raw_order["name"]),
            False,
        )
        position.send_line_exe = False
        position.order_plan_registration(order)
        submitted: list[str] = []

        def _record_submit():
            submitted.append("submit_order")
            position.waiting_order = False
            position.watching_for_position_done = True
            position.o_state = "PENDING"
            position.o_id = "order-1"
            return {
                "order_name": position.name,
                "order_id": position.o_id,
                "order_result": {},
            }

        position.watching_for_position_make_order = _record_submit
        events = []
        for tick in position_spec["ticks"]:
            _FrozenDateTime.current = datetime.fromisoformat(str(tick["at"]))
            position.oa.now_price_queue = [
                {
                    "ask": float(tick["price"]),
                    "bid": float(tick["price"]),
                    "mid": float(tick["price"]),
                    "spread": 0.0,
                }
            ]
            before_submits = len(submitted)
            before_life = bool(position.life)
            position.watching_for_position(None)
            commands = []
            emitted = []
            if len(submitted) > before_submits:
                commands.append({"action": "submit_order"})
                emitted.append("order_submitted")
            if before_life and not position.life:
                commands.append({"action": "cancel_watching"})
                emitted.append("order_cancelled")
            events.append(
                {
                    "kind": "position_tick",
                    "at": _FrozenDateTime.current.isoformat(),
                    "price": float(tick["price"]),
                    "slot": _legacy_watching_slot(position),
                    "commands": commands,
                    "events": emitted,
                }
            )
    finally:
        classPosition.datetime.datetime = original_datetime

    return {
        "pair": scenario.pair,
        "kind": scenario.kind,
        "scenario_id": scenario.scenario_id,
        "events": events,
    }


def _legacy_watching_slot(position) -> dict[str, Any]:
    if not position.life:
        order_state = "CANCELLED"
    elif position.waiting_order:
        order_state = "WATCHING"
    elif position.o_state == "PENDING":
        order_state = "PENDING"
    else:
        order_state = str(position.o_state).upper() or "REGISTERED"
    return {
        "name": position.name,
        "life": bool(position.life),
        "waiting_order": bool(position.waiting_order and position.life),
        "order_state": order_state,
        "trade_state": "NONE",
        "step1_started_at": (
            position.step1_filled_time.isoformat()
            if position.step1_filled and not isinstance(position.step1_filled_time, int)
            else None
        ),
        "step2_started_at": (
            position.step2_filled_time.isoformat()
            if position.step2_filled and not isinstance(position.step2_filled_time, int)
            else None
        ),
    }


def _run_position_pending_timeout(scenario: DifferentialScenario) -> dict[str, Any]:
    classOrderCreate = importlib.import_module("classOrderCreate")
    classPosition = importlib.import_module("classPosition")
    _assert_module_paths(
        {
            "classOrderCreate": classOrderCreate,
            "classPosition": classPosition,
        }
    )
    spec = scenario.payload["position"]
    order_spec = dict(spec["order"])
    order_spec.setdefault("pair", scenario.pair)
    order_spec.setdefault("decision_time", scenario.payload["decision_time"])
    order_spec.setdefault(
        "candle_analysis_class",
        _LegacyCandleAnalysisStub(float(order_spec["current_price"])),
    )
    order = classOrderCreate.Order(order_spec)
    plan = dict(order.exe_order_plan)
    first_at = datetime.fromisoformat(str(spec["ticks"][0]["at"]))

    class _FrozenDateTime(datetime):
        current = first_at

        @classmethod
        def now(cls, tz=None):
            if tz is None:
                return cls.current
            return tz.fromutc(cls.current.replace(tzinfo=tz))

    original_datetime = classPosition.datetime.datetime
    classPosition.datetime.datetime = _FrozenDateTime
    try:
        position = classPosition.order_information(str(plan["name"]), False)
        position.send_line_exe = False
        position.life = True
        position.waiting_order = False
        position.o_id = "order-1"
        position.o_state = "PENDING"
        position.order_timeout_min = int(plan["order_timeout_min"])
        position.order_register_time = first_at
        position.plan_json = plan
        position.for_api_json = dict(plan["for_api_json"])
        if "broker_steps" in scenario.payload:
            position.oa.set_broker_steps(scenario.payload["broker_steps"])
        events = []
        for tick in spec["ticks"]:
            _FrozenDateTime.current = datetime.fromisoformat(str(tick["at"]))
            elapsed = (_FrozenDateTime.current - first_at).total_seconds()
            action_offset = len(position.oa.broker_actions)
            if "broker_steps" in scenario.payload:
                order_response = position.oa.OrderDetails_exe(position.o_id)
                if order_response.get("error"):
                    raise ValueError("pending-timeout order response was not found")
                position.o_json = order_response["data"]["order"]
                position.o_time_past_sec = float(
                    position.o_json.get("time_past", elapsed)
                )
            else:
                position.o_json = {
                    "state": "PENDING",
                    "time_past": elapsed,
                }
                position.o_time_past_sec = elapsed
            before_life = position.life
            position.order_update_and_close()
            commands = []
            emitted = []
            if before_life and not position.life:
                commands.append({"action": "cancel_order"})
                emitted.append("order_cancelled")
            events.append(
                {
                    "kind": "position_tick",
                    "at": _FrozenDateTime.current.isoformat(),
                    "price": float(tick["price"]),
                    "slot": {
                        "name": position.name,
                        "life": bool(position.life),
                        "order_state": "PENDING" if position.life else "CANCELLED",
                        "trade_state": "NONE",
                    },
                    "commands": commands,
                    "events": emitted,
                    "broker_actions": position.oa.broker_actions[action_offset:],
                }
            )
        position.oa.assert_broker_steps_consumed()
    finally:
        classPosition.datetime.datetime = original_datetime
    return {
        "pair": scenario.pair,
        "kind": scenario.kind,
        "scenario_id": scenario.scenario_id,
        "events": events,
    }


def _run_position_lc_change(scenario: DifferentialScenario) -> dict[str, Any]:
    classOrderCreate = importlib.import_module("classOrderCreate")
    classPosition = importlib.import_module("classPosition")
    _assert_module_paths(
        {
            "classOrderCreate": classOrderCreate,
            "classPosition": classPosition,
        }
    )
    spec = scenario.payload["position"]
    order_spec = dict(spec["order"])
    order_spec.setdefault("pair", scenario.pair)
    order_spec.setdefault("decision_time", scenario.payload["decision_time"])
    order_spec.setdefault(
        "candle_analysis_class",
        _LegacyCandleAnalysisStub(float(order_spec["current_price"])),
    )
    order = classOrderCreate.Order(order_spec)
    plan = dict(order.exe_order_plan)
    first_at = datetime.fromisoformat(str(spec["ticks"][0]["at"]))

    class _FrozenDateTime(datetime):
        current = first_at

        @classmethod
        def now(cls, tz=None):
            if tz is None:
                return cls.current
            return tz.fromutc(cls.current.replace(tzinfo=tz))

    original_datetime = classPosition.datetime.datetime
    classPosition.datetime.datetime = _FrozenDateTime
    try:
        position = classPosition.order_information(str(plan["name"]), False)
        position.send_line_exe = False
        position.life = True
        position.t_state = "OPEN"
        position.t_id = "trade-1"
        position.t_execution_price = float(plan["target_price"])
        position.plan_json = plan
        position.lc_change_dic_arr = [dict(rule) for rule in plan["lc_change"]]
        events = []
        for tick in spec["ticks"]:
            _FrozenDateTime.current = datetime.fromisoformat(str(tick["at"]))
            position.t_time_past_sec = (
                _FrozenDateTime.current - first_at
            ).total_seconds()
            direction = int(plan["direction"])
            position.t_price_diff = (
                float(tick["price"]) - float(plan["target_price"])
            ) * direction
            before_calls = len(position.oa.crcdo_calls)
            position.lc_change()
            commands = [
                {
                    "action": "amend_stop_loss",
                    "stop_loss_price": float(call["data"]["stopLoss"]["price"]),
                }
                for call in position.oa.crcdo_calls[before_calls:]
            ]
            events.append(
                {
                    "kind": "position_tick",
                    "at": _FrozenDateTime.current.isoformat(),
                    "price": float(tick["price"]),
                    "slot": {
                        "name": position.name,
                        "life": bool(position.life),
                        "order_state": "FILLED",
                        "trade_state": "OPEN",
                        "current_stop_loss": float(position.plan_json["lc_price"]),
                        "applied_rule_count": int(position.lc_change_num),
                    },
                    "commands": commands,
                    "events": [],
                }
            )
    finally:
        classPosition.datetime.datetime = original_datetime
    return {
        "pair": scenario.pair,
        "kind": scenario.kind,
        "scenario_id": scenario.scenario_id,
        "events": events,
    }


def _run_portfolio_acceptance(scenario: DifferentialScenario) -> dict[str, Any]:
    classOrderCreate = importlib.import_module("classOrderCreate")
    classPositionControl = importlib.import_module("classPositionControl")
    _assert_module_paths(
        {
            "classOrderCreate": classOrderCreate,
            "classPositionControl": classPositionControl,
        }
    )
    controller = classPositionControl.position_control(False, scenario.pair)
    events = []
    for batch_index, batch in enumerate(scenario.payload["position"]["batches"]):
        order_specs = []
        for raw in batch:
            order_spec = dict(raw)
            order_spec.setdefault("pair", scenario.pair)
            order_spec.setdefault("decision_time", scenario.payload["decision_time"])
            order_spec.setdefault("order_permission", False)
            order_spec.setdefault("lc_change", [])
            order_spec.setdefault(
                "candle_analysis_class",
                _LegacyCandleAnalysisStub(float(order_spec["current_price"])),
            )
            order_specs.append(order_spec)
        orders = [classOrderCreate.Order(spec) for spec in order_specs]
        filtered = controller.filter_similar_order_classes(orders, threshold_pips=3)
        filtered_names = {
            order.exe_order_plan["name"] for order in filtered
        }
        before = {
            slot.name for slot in controller.position_classes if slot.life
        }
        controller.order_class_add(orders)
        after = {
            slot.name for slot in controller.position_classes if slot.life
        }
        accepted = [
            order.exe_order_plan["name"]
            for order in orders
            if order.exe_order_plan["name"] in after - before
        ]
        rejected = []
        for order in orders:
            name = order.exe_order_plan["name"]
            if name in accepted:
                continue
            reason = "duplicate" if name not in filtered_names else "tier_full"
            rejected.append({"name": name, "reason": reason})
        events.append(
            {
                "kind": "portfolio_batch",
                "batch_index": batch_index,
                "accepted": accepted,
                "rejected": rejected,
                "slots": [
                    {
                        "index": index,
                        "name": slot.name,
                        "priority": int(slot.priority),
                    }
                    for index, slot in enumerate(controller.position_classes)
                    if slot.life
                ],
            }
        )
    return {
        "pair": scenario.pair,
        "kind": scenario.kind,
        "scenario_id": scenario.scenario_id,
        "events": events,
    }


def _legacy_order_from_position_spec(scenario: DifferentialScenario):
    classOrderCreate = importlib.import_module("classOrderCreate")
    raw = dict(scenario.payload["position"]["order"])
    raw.setdefault("pair", scenario.pair)
    raw.setdefault("decision_time", scenario.payload["decision_time"])
    raw.setdefault("lc_change", [])
    raw.setdefault(
        "candle_analysis_class",
        _LegacyCandleAnalysisStub(float(raw["current_price"])),
    )
    return classOrderCreate.Order(raw)


def _run_broker_outcome(scenario: DifferentialScenario) -> dict[str, Any]:
    classPosition = importlib.import_module("classPosition")
    _assert_module_paths({"classPosition": classPosition})
    spec = scenario.payload["position"]
    outcome = str(spec["outcome"])
    order = _legacy_order_from_position_spec(scenario)
    position = classPosition.order_information(order.exe_order_plan["name"], False)
    position.send_line_exe = False
    submit_count = 0
    raw_broker_steps = scenario.payload.get("broker_steps")
    if raw_broker_steps is not None:
        position.oa.set_broker_steps(raw_broker_steps)

    if raw_broker_steps is None and outcome == "reject":
        def _reject(_payload):
            nonlocal submit_count
            submit_count += 1
            return {"data": {"cancel": True, "order_id": 0}}

        position.oa.OrderCreate_dic_exe = _reject
    elif raw_broker_steps is None and outcome == "exception":
        def _raise(_payload):
            nonlocal submit_count
            submit_count += 1
            raise RuntimeError(str(spec.get("message", "scripted broker exception")))

        position.oa.OrderCreate_dic_exe = _raise
    elif raw_broker_steps is None:
        original_submit = position.oa.OrderCreate_dic_exe

        def _accepted(payload):
            nonlocal submit_count
            submit_count += 1
            return original_submit(payload)

        position.oa.OrderCreate_dic_exe = _accepted

    error: str | None = None
    query_events = []
    try:
        if raw_broker_steps is not None or outcome in {"reject", "exception"}:
            position.order_class = order
            position.plan_json = dict(order.exe_order_plan)
            position.for_api_json = dict(order.exe_order_plan["for_api_json"])
            position.name = str(order.exe_order_plan["name"])
            registration = position.make_order()
            if raw_broker_steps is not None:
                submit_count = position.oa.broker_actions.count("submit")
        else:
            position.order_class = order
            position.plan_json = dict(order.exe_order_plan)
            position.for_api_json = dict(order.exe_order_plan["for_api_json"])
            position.name = str(order.exe_order_plan["name"])
            position.life = True
            position.o_id = "order-1"
            position.o_state = "PENDING"
            submit_count = 1
            registration = {"order_id": position.o_id}
        accepted = bool(registration.get("order_id"))
        if outcome == "not_found":
            if raw_broker_steps is None:
                position.oa.OrderDetails_exe = lambda _order_id: {"error": 1}
            for attempt in range(1, int(spec.get("query_attempts", 4)) + 1):
                position.update_information(None)
                query_events.append(
                    {
                        "attempt": attempt,
                        "life": bool(position.life),
                        "order_state": (
                            "PENDING" if position.life else "CANCELLED"
                        ),
                        "reason": "broker_snapshot_missing",
                    }
                )
    except RuntimeError as caught:
        accepted = False
        error = str(caught)

    if raw_broker_steps is not None:
        submit_count = position.oa.broker_actions.count("submit")

    event = {
        "kind": "broker_outcome",
        "outcome": outcome,
        "accepted": accepted,
        "life": bool(position.life),
        "order_state": (
            "PENDING"
            if position.life
            else "ERROR"
            if error
            else "CANCELLED"
            if outcome == "not_found"
            else "REJECTED"
        ),
        "submit_count": submit_count,
        "error": error,
        "queries": query_events,
        "broker_actions": list(position.oa.broker_actions),
    }
    position.oa.assert_broker_steps_consumed()
    return {
        "pair": scenario.pair,
        "kind": scenario.kind,
        "scenario_id": scenario.scenario_id,
        "events": [event],
    }


def _run_linkage_hedge(scenario: DifferentialScenario) -> dict[str, Any]:
    classPosition = importlib.import_module("classPosition")
    classPositionControl = importlib.import_module("classPositionControl")
    _assert_module_paths(
        {
            "classPosition": classPosition,
            "classPositionControl": classPositionControl,
        }
    )
    events = []
    for check in scenario.payload["position"]["checks"]:
        if check == "pending_cancel":
            main = classPosition.order_information("main-filled", False)
            linked = classPosition.order_information("linked-pending", False)
            linked.name = "linked-pending"
            linked.o_state = "PENDING"
            linked.life = True
            calls = []
            linked.close_order = lambda: calls.append("linked-pending")
            main.linkage_class_slots = [linked]
            main.linkage_change_order_from_detect_change()
            commands = [
                {"action": "cancel_order", "position_id": name}
                for name in calls
            ]
        elif check == "loss_lc":
            main = classPosition.order_information("main-loss", False)
            linked = classPosition.order_information("linked-open", False)
            main.plan_json = {"direction": 1}
            main.t_price_diff = -0.03
            linked.life = True
            linked.t_state = "OPEN"
            linked.t_id = "trade-linked"
            linked.plan_json = {
                "direction": -1,
                "target_price": 150.0,
                "lc_range": 0.05,
                "lc_price": 150.2,
            }
            main.linkage_class_slots = [linked]
            main.linkage_change_trade_from_detect_change()
            commands = [
                {
                    "action": "amend_stop_loss",
                    "position_id": "linked-open",
                    "stop_loss_price": float(
                        call["data"]["stopLoss"]["price"]
                    ),
                }
                for call in linked.oa.crcdo_calls
            ]
        elif check == "hedge_noop":
            calls = []

            class _HedgePosition:
                def __init__(self, name, direction):
                    self.name = name
                    self.life = True
                    self.t_unrealize_pl = 0.3
                    self.plan_json = {
                        "target_price": 150.0,
                        "direction": direction,
                        "units": 1000,
                    }

                def close_trade(self):
                    calls.append(self.name)

            controller = object.__new__(classPositionControl.position_control)
            controller.position_classes = [
                _HedgePosition("long", 1),
                _HedgePosition("short", -1),
            ]
            classPositionControl.tk.setting_json["hedge_close_on"] = False
            controller.close_hedge_positions()
            commands = [
                {"action": "close_trade", "position_id": name}
                for name in calls
            ]
        else:
            raise LegacyRunnerError(f"Unsupported linkage/hedge check: {check}")
        events.append(
            {
                "kind": "position_policy",
                "check": check,
                "commands": commands,
            }
        )
    return {
        "pair": scenario.pair,
        "kind": scenario.kind,
        "scenario_id": scenario.scenario_id,
        "events": events,
    }


def _run_close_reporting(scenario: DifferentialScenario) -> dict[str, Any]:
    classPosition = importlib.import_module("classPosition")
    _assert_module_paths({"classPosition": classPosition})
    spec = scenario.payload["position"]
    fixed_now = datetime.fromisoformat(
        str(scenario.payload["decision_time"]).replace("/", "-")
    )

    class _FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            if tz is None:
                return fixed_now
            return tz.fromutc(fixed_now.replace(tzinfo=tz))

    original_datetime = classPosition.datetime.datetime
    classPosition.datetime.datetime = _FrozenDateTime
    position_class = classPosition.order_information
    for name, value in {
        "total_yen": 0,
        "total_yen_max": 0,
        "total_yen_min": float("inf"),
        "total_price_diff": 0,
        "total_price_diff_max": 0,
        "total_price_diff_min": float("inf"),
        "total_pips": 0,
        "total_pips_max": 0,
        "total_pips_min": float("inf"),
        "plus_yen_position_num": 0,
        "minus_yen_position_num": 0,
        "lc_change_num": 0,
        "before_latest_price_diff": 0,
        "before_latest_pl_pips": 0,
        "before_latest_plu": 0,
        "before_latest_name": "",
    }.items():
        setattr(position_class, name, value)
    position_class.result_dic_arr = []
    position_class.history_plus_minus = [0]
    position_class.history_names = ["0"]
    position_class.history_name_plus_minus = []

    position = position_class(str(spec["name"]), False)
    notifications: list[str] = []
    history_rows: list[dict[str, Any]] = []
    history_file = tempfile.NamedTemporaryFile(
        prefix="ogami-differential-history-",
        suffix=".csv",
        delete=False,
    )
    history_path = Path(history_file.name)
    history_file.close()
    history_path.unlink(missing_ok=True)
    position.send_line = lambda *args: notifications.append(
        " ".join(str(item) for item in args)
    )

    def _write_history(result):
        history_rows.append(dict(result))
        classPosition.pd.DataFrame(history_rows).to_csv(history_path, index=False)
        return str(history_path)

    position.write_history_result = _write_history
    position.life = True
    position.pair = scenario.pair
    position.o_id = str(spec["order_id"])
    position.t_id = str(spec["trade_id"])
    position.o_time = "2026/01/02 09:00:00"
    position.t_time = "2026/01/02 09:10:00"
    position.name_ymdhms = str(spec.get("name_ymdhms", spec["name"]))
    position.plan_json = {
        "direction": int(spec.get("direction", 1)),
        "target_price": float(spec["target_price"]),
        "lc_price": float(spec.get("lc_price", 149.95)),
        "lc_price_original": float(spec.get("lc_price_original", 149.9)),
        "lc_range": float(spec.get("lc_range", 0.1)),
        "tp_price": float(spec.get("tp_price", 150.25)),
        "tp_price_original": float(spec.get("tp_price_original", 150.3)),
        "tp_range": float(spec.get("tp_range", 0.2)),
        "memo": str(spec.get("memo", "close memo")),
    }
    position.for_line_send_order_info_at_close = "close summary"
    position.positions_information = {
        "open_positions": [],
        "pending_positions": [],
    }
    position.order_class = types.SimpleNamespace(memo="order memo")
    position.move_ave5 = 0.05
    position.move_ave60 = 0.15
    position.current_candle_price_gap = 0.02
    position.gap_target_price_pips = 3.5
    position.win_max_pips = 12
    position.lose_max_pips = -4
    position.win_max_price = 150.22
    position.lose_max_price = 149.96
    position.win_max_price_diff_yen = 1200
    position.lose_max_price_diff_yen = -400
    position.lc_change_str = "(3p-1p)"
    position.t_json = {
        "state": "CLOSED",
        "realizedPL": str(spec["realized_pl"]),
        "price": str(spec["target_price"]),
        "averageClosePrice": str(spec["close_price"]),
        "initialUnits": str(spec["units"]),
        "currentUnits": "0",
        "time_past": 600,
    }
    try:
        position.after_close_trade_function()
        if position.life:
            position.after_close_trade_function()
        with history_path.open(newline="", encoding="utf-8") as stream:
            reader = csv.DictReader(stream)
            csv_rows = list(reader)
            csv_columns = list(reader.fieldnames or ())
    finally:
        history_path.unlink(missing_ok=True)
        classPosition.datetime.datetime = original_datetime
    event = {
        "kind": "close_reporting",
        "close_event_count": len(history_rows),
        "history": {
            "columns": csv_columns,
            "rows": [
                [builtin_value(row[column]) for column in csv_columns]
                for row in csv_rows
            ],
        },
        "notifications": notifications,
        "analytics": {
            "total_yen": position_class.total_yen,
            "total_pips": position_class.total_pips,
            "plus_count": position_class.plus_yen_position_num,
            "minus_count": position_class.minus_yen_position_num,
            "latest_name": position_class.before_latest_name,
        },
    }
    return {
        "pair": scenario.pair,
        "kind": scenario.kind,
        "scenario_id": scenario.scenario_id,
        "events": [event],
    }


def _run_trade_timeout_disabled(scenario: DifferentialScenario) -> dict[str, Any]:
    classPosition = importlib.import_module("classPosition")
    _assert_module_paths({"classPosition": classPosition})
    spec = scenario.payload["position"]
    order = spec["order"]
    position = classPosition.order_information(str(order["name"]), False)
    position.life = True
    position.trade_timeout_min = int(order.get("trade_timeout_min", 1))
    close_calls = []
    position.close_trade = lambda units=None: close_calls.append(units)
    events = []
    for tick in spec["ticks"]:
        position.current_price = float(tick["price"])
        position.t_json = {
            "id": "trade-timeout",
            "state": "OPEN",
            "initialUnits": str(order["units"]),
            "currentUnits": str(order["units"]),
            "openTime": scenario.payload["decision_time"],
            "time_past": int(tick["elapsed_seconds"]),
            "price": str(order["target"]),
            "unrealizedPL": str(tick.get("unrealized_pl", 0)),
        }
        before = len(close_calls)
        position.trade_update_and_close()
        events.append(
            {
                "kind": "position_tick",
                "elapsed_seconds": int(tick["elapsed_seconds"]),
                "commands": [
                    {"action": "close_trade"}
                    for _call in close_calls[before:]
                ],
                "slot": {
                    "life": bool(position.life),
                    "trade_state": position.t_state,
                },
            }
        )
    return {
        "pair": scenario.pair,
        "kind": scenario.kind,
        "scenario_id": scenario.scenario_id,
        "events": events,
    }


def _run_candle_lc(scenario: DifferentialScenario) -> dict[str, Any]:
    import pandas as pd

    classPosition = importlib.import_module("classPosition")
    _assert_module_paths({"classPosition": classPosition})
    spec = scenario.payload["position"]
    order = spec["order"]
    first_at = datetime.fromisoformat(str(spec["ticks"][0]["at"]))

    class _FrozenDateTime(datetime):
        current = first_at

        @classmethod
        def now(cls, tz=None):
            if tz is None:
                return cls.current
            return tz.fromutc(cls.current.replace(tzinfo=tz))

    original_datetime = classPosition.datetime.datetime
    classPosition.datetime.datetime = _FrozenDateTime
    try:
        position = classPosition.order_information(str(order["name"]), False)
        position.t_state = "OPEN"
        position.t_id = "trade-candle"
        position.t_execution_price = float(order["target"])
        position.t_json = {"price": float(order["target"])}
        position.plan_json = {
            "direction": int(order["direction"]),
            "lc_price": float(order["lc_price"]),
            "target_price": float(order["target"]),
        }
        peak = types.SimpleNamespace(
            peaks_original=[dict(spec["latest_peak"])],
            df_r_original=pd.DataFrame(
                [
                    dict(spec["previous_candle"]),
                    dict(spec["previous_candle"]),
                ]
            ),
        )
        candle = types.SimpleNamespace(peaks_class=peak, peaks_class_hour=peak)
        events = []
        for tick in spec["ticks"]:
            _FrozenDateTime.current = datetime.fromisoformat(str(tick["at"]))
            position.t_time_past_sec = int(tick["elapsed_seconds"])
            before = len(position.oa.crcdo_calls)
            position.lc_change_from_candle(candle)
            commands = [
                {
                    "action": "amend_stop_loss",
                    "stop_loss_price": float(call["data"]["stopLoss"]["price"]),
                }
                for call in position.oa.crcdo_calls[before:]
            ]
            events.append(
                {
                    "kind": "position_tick",
                    "elapsed_seconds": int(tick["elapsed_seconds"]),
                    "commands": commands,
                    "slot": {
                        "current_stop_loss": float(position.plan_json["lc_price"]),
                        "candle_lc_done": bool(position.lc_change_candle_done),
                    },
                }
            )
    finally:
        classPosition.datetime.datetime = original_datetime
    return {
        "pair": scenario.pair,
        "kind": scenario.kind,
        "scenario_id": scenario.scenario_id,
        "events": events,
    }


def _run_restore(scenario: DifferentialScenario) -> dict[str, Any]:
    classPosition = importlib.import_module("classPosition")
    classPositionControl = importlib.import_module("classPositionControl")
    _assert_module_paths(
        {
            "classPosition": classPosition,
            "classPositionControl": classPositionControl,
        }
    )
    spec = scenario.payload["position"]
    fixed_now = datetime.fromisoformat(
        str(scenario.payload["decision_time"]).replace("/", "-")
    )

    class _FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            if tz is None:
                return fixed_now
            return tz.fromutc(fixed_now.replace(tzinfo=tz))

    original_datetime = classPosition.datetime.datetime
    classPosition.datetime.datetime = _FrozenDateTime
    try:
        controller = classPositionControl.position_control(False, scenario.pair)
        initial_slots = spec["initial_slots"]
        for index, initial in enumerate(initial_slots):
            if initial is None:
                continue
            controller.position_classes[index].life = bool(initial.get("life", True))
            controller.position_classes[index].name = str(initial["name"])
        occupied = sum(item is not None for item in initial_slots)
        trades = [dict(item) for item in spec["broker_positions"]]
        controller.oa2.OpenTrades_exe = lambda: {
            "data": trades,
            "json": {"trades": trades},
        }
        controller.catch_up_position_and_del_order()
        slots = [
            {
                "index": index,
                "name": slot.name,
                "trade_id": str(slot.t_id),
                "direction": int(slot.plan_json.get("direction", 0)),
                "target_price": float(slot.plan_json.get("target_price", 0)),
            }
            for index, slot in enumerate(controller.position_classes)
            if slot.life and index >= occupied
        ]
    finally:
        classPosition.datetime.datetime = original_datetime
    return {
        "pair": scenario.pair,
        "kind": scenario.kind,
        "scenario_id": scenario.scenario_id,
        "events": [{"kind": "restore", "slots": slots}],
    }


def _run_active_dedup(scenario: DifferentialScenario) -> dict[str, Any]:
    import fGeneric

    classPositionControl = importlib.import_module("classPositionControl")
    _assert_module_paths({"classPositionControl": classPositionControl})
    spec = scenario.payload["position"]

    class _ActiveSlot:
        def __init__(self, item):
            self.name = item["name"]
            self.life = True
            self.plan_json = dict(item)
            self.o_state = "PENDING"
            self.t_state = ""

    controller = object.__new__(classPositionControl.position_control)
    controller.pair = scenario.pair
    controller.p = fGeneric.currency_pair(scenario.pair)
    controller.position_classes = [
        _ActiveSlot(item) for item in spec["active"]
    ]
    candidate = spec["candidate"]
    result = controller.find_similar_active_order(
        int(candidate["direction"]),
        float(candidate["target_price"]),
        int(candidate.get("threshold_pips", 3)),
        source=candidate.get("source"),
        line_strategy=candidate.get("line_strategy"),
    )
    event = {
        "kind": "active_dedup",
        "is_exist": bool(result["is_exist"]),
        "name": result.get("name"),
        "gap_pips": result.get("gap_pips"),
        "source": result.get("source"),
        "line_strategy": result.get("line_strategy"),
    }
    return {
        "pair": scenario.pair,
        "kind": scenario.kind,
        "scenario_id": scenario.scenario_id,
        "events": [event],
    }


def _run_live_schedule(scenario: DifferentialScenario) -> dict[str, Any]:
    main_exe = importlib.import_module("main_exe")
    import fGeneric

    _assert_module_paths({"main_exe": main_exe, "fGeneric": fGeneric})

    live = scenario.payload["live"]

    class _FrozenDateTime(datetime):
        current = datetime.fromisoformat(str(live["ticks"][0]["now"]))

        @classmethod
        def now(cls, tz=None):
            if tz is None:
                return cls.current
            return tz.fromutc(cls.current.replace(tzinfo=tz))

    original_datetime = main_exe.datetime.datetime
    main_exe.datetime.datetime = _FrozenDateTime
    fGeneric.set_current_pair(scenario.pair)
    app = main_exe.main()
    if live.get("first_exe") is not None:
        app.first_exe = bool(live["first_exe"])
    if live.get("latest_exe_time"):
        app.latest_exe_time = datetime.fromisoformat(str(live["latest_exe_time"]))

    call_sequence: list[str] = []
    app.base_oa.trace = call_sequence
    live_counts = {"plans": 0, "accepted": 0, "rejected": 0}

    class _Candle:
        def update_s5_df(self, *_args, **_kwargs):
            return None

    class _Positions:
        def __init__(self):
            self.oa2 = _LegacyFakeOanda("test", "test", "practice")
            self.oa2.trace = call_sequence

        def all_update_information_at_out_time(self):
            call_sequence.append("sync")
            return {}

        def all_update_information(self, *_args, **_kwargs):
            call_sequence.append("sync")
            return {
                "open_positions": [],
                "watching_list": [],
            }

        def life_check(self):
            return {"life_exist": False, "one_line_comment": ""}

        def order_class_add(self, order_classes):
            call_sequence.append("register")
            live_counts["accepted"] = len(order_classes)
            return ["registered"] * len(order_classes)

    class _AnalysisResult:
        def __init__(self):
            candidate_count = int(live.get("candidate_count", 0))
            self.take_position_flag = candidate_count > 0
            self.exe_order_classes = [object() for _ in range(candidate_count)]
            live_counts["plans"] = candidate_count

    class _AnalysisModule:
        @staticmethod
        def wrap_all_analysis(*_args, **_kwargs):
            call_sequence.append("analysis")
            return _AnalysisResult()

    app.positions_control_class = _Positions()
    app.candleAnalysisClass = _Candle()
    main_exe.ca.candleAnalysis = lambda *_args, **_kwargs: _Candle()
    main_exe.am = _AnalysisModule()

    events = []
    try:
        startup_orders = list(live.get("startup_pending_orders", ()))
        if startup_orders and live.get("cancel_pending_on_start", False):
            app.positions_control_class.oa2.orders = {
                str(item["order_id"]): {
                    "id": str(item["order_id"]),
                    "state": "PENDING",
                }
                for item in startup_orders
            }
            call_sequence.clear()
            app.positions_control_class.oa2.OrderCancel_All_exe()
            events.append(
                {
                    "kind": "live_startup",
                    "sequence": ["cancel_pending"],
                    "cancelled_order_ids": sorted(
                        str(item["order_id"]) for item in startup_orders
                    ),
                }
            )
        for tick in live["ticks"]:
            now = datetime.fromisoformat(str(tick["now"]))
            _FrozenDateTime.current = now
            app.now = now
            app.time_hour = now.hour
            app.time_min = now.minute
            app.time_sec = now.second
            app.base_oa.price_response_queue = [dict(tick["price_response"])]
            app.base_oa.last_quote = None
            call_sequence.clear()
            live_counts.update(plans=0, accepted=0, rejected=0)
            app.exe_manage()
            sequence = list(call_sequence)
            quote = app.base_oa.last_quote
            spread = float(quote["spread"]) if quote is not None else 0.0
            update_only = (
                (now.weekday() == 5 and now.hour >= 4)
                or (now.weekday() == 0 and now.hour <= 7)
                or spread > app.ARROW_SPREAD
            )
            if now.weekday() == 6:
                decision = "market_closed"
            elif "analysis" in sequence:
                decision = "analyze"
            elif update_only:
                decision = "update_only"
            else:
                decision = "idle"
            events.append(
                {
                    "kind": "live_tick",
                    "now": now.isoformat(),
                    "decision": decision,
                    "sequence": sequence,
                    "quote_count": sequence.count("quote"),
                    "quote": dict(quote) if quote is not None else None,
                    "plan_count": live_counts["plans"],
                    "accepted_count": live_counts["accepted"],
                    "rejected_count": live_counts["rejected"],
                }
            )
    finally:
        main_exe.datetime.datetime = original_datetime

    return {
        "pair": scenario.pair,
        "kind": scenario.kind,
        "scenario_id": scenario.scenario_id,
        "events": events,
    }


class _LegacyFakeOanda:
    def __init__(self, accountID, access_token, env):
        self.account_id = accountID
        self.access_token = access_token
        self.environment = env
        self.now_price_queue: list[dict[str, float]] = []
        self.price_response_queue: list[dict[str, Any]] = []
        self.last_quote: dict[str, Any] | None = None
        self.orders: dict[str, dict[str, Any]] = {}
        self.trades: dict[str, dict[str, Any]] = {}
        self.created_payloads: list[dict[str, Any]] = []
        self.crcdo_calls: list[dict[str, Any]] = []
        self.broker_steps: list[dict[str, Any]] | None = None
        self.broker_actions: list[str] = []

    def set_broker_steps(self, steps) -> None:
        self.broker_steps = [
            dict(step)
            for step in steps
            if step.get("runner") in {None, "both", "legacy"}
        ]

    def assert_broker_steps_consumed(self) -> None:
        if self.broker_steps:
            actions = [str(step.get("action")) for step in self.broker_steps]
            raise ValueError(f"Legacy broker has unconsumed steps: {actions}")

    def _consume_broker_response(self, action: str) -> dict[str, Any] | None:
        if self.broker_steps is None:
            return None
        if not self.broker_steps:
            raise ValueError(f"Legacy broker step underflow for action {action}")
        step = self.broker_steps.pop(0)
        actual = str(step.get("action"))
        if actual != action:
            raise ValueError(
                f"Legacy broker action mismatch: expected {actual}, got {action}"
            )
        response = step.get("response")
        if not isinstance(response, Mapping):
            raise ValueError(f"Legacy broker {action} response must be an object")
        self.broker_actions.append(action)
        if response.get("exception") is not None:
            raise RuntimeError(str(response["exception"]))
        return dict(response)

    def NowPrice_exe(self, instrument):
        trace = getattr(self, "trace", None)
        if trace is not None:
            trace.append("quote")
        if self.price_response_queue:
            response = self.price_response_queue.pop(0)
            price = response["prices"][0]
            pair = importlib.import_module("fGeneric").currency_pair(instrument)
            bid = pair.round_price(float(price["bids"][0]["price"]))
            ask = pair.round_price(float(price["asks"][0]["price"]))
            payload = {
                "bid": bid,
                "ask": ask,
                "mid": pair.round_price((bid + ask) / 2),
                "spread": pair.round_price(ask - bid),
                "tradeable": str(price.get("status", "tradeable")).lower()
                == "tradeable",
            }
        elif self.now_price_queue:
            payload = self.now_price_queue.pop(0)
        else:
            mid = 150.0 if instrument.endswith("JPY") else 1.1
            payload = {
                "bid": mid,
                "ask": mid,
                "mid": mid,
                "spread": 0.0,
                "tradeable": True,
            }
        self.last_quote = dict(payload)
        return {"error": 0, "data": payload}

    def InstrumentsCandles_multi_exe(self, pair, params, roop):
        granularity = str(params.get("granularity", "M5"))
        frame = _legacy_frame_store(pair).get(granularity)
        if frame is None:
            frame = _legacy_frame_store(pair)["M5"]
        return {"error": 0, "data": frame}

    def OrderCreate_dic_exe(self, payload):
        self.created_payloads.append(payload)
        response = self._consume_broker_response("submit")
        if response is not None and str(response.get("state", "PENDING")).upper() in {
            "REJECTED",
            "CANCELLED",
            "TERMINAL",
        }:
            return {
                "data": {
                    "cancel": True,
                    "order_id": 0,
                    "reason": str(response.get("reason", "scripted rejection")),
                }
            }
        order_id = str(
            response.get("order_id", 1000 + len(self.created_payloads))
            if response is not None
            else 1000 + len(self.created_payloads)
        )
        order = {
            "id": order_id,
            "state": "PENDING",
            "tradeOpenedID": None,
            "price": payload["order"].get("price", "0"),
            "units": payload["order"].get("units", "0"),
            "instrument": payload["order"].get("instrument", "USD_JPY"),
        }
        self.orders[order_id] = order
        return {
            "data": {
                "cancel": False,
                "order_id": order_id,
                "order_time": "2026/01/02 12:00:00",
                "price": order["price"],
                "execution_price": order["price"],
                "json": {
                    "orderCreateTransaction": {
                        "units": order["units"],
                        "price": order["price"],
                        "takeProfitOnFill": payload["order"].get("takeProfitOnFill", {}),
                        "stopLossOnFill": payload["order"].get("stopLossOnFill", {}),
                    }
                },
            }
        }

    def OrderDetails_exe(self, order_id):
        response = self._consume_broker_response("order")
        if response is not None:
            if response.get("found", True) is False:
                return {"error": 1}
            order = {
                "id": str(response.get("order_id", order_id)),
                "state": str(response.get("state", "PENDING")).upper(),
                "tradeOpenedID": response.get("trade_id"),
                "time_past": float(response.get("elapsed_seconds", 0.0)),
            }
            return {"error": 0, "data": {"order": order}}
        order = self.orders.get(str(order_id))
        if order is None:
            return {"error": 0, "data": {"order": {"id": str(order_id), "state": "CANCELLED"}}}
        return {"error": 0, "data": {"order": order}}

    def TradeDetails_exe(self, trade_id):
        response = self._consume_broker_response("trade")
        if response is not None:
            if response.get("found", True) is False:
                return {"error": 1}
            trade = {
                "id": str(response.get("trade_id", trade_id)),
                "state": str(response.get("state", "OPEN")).upper(),
                "price": str(response.get("price", "150.0")),
                "currentUnits": str(response.get("units", "1000")),
                "initialUnits": str(response.get("units", "1000")),
                "unrealizedPL": str(response.get("unrealized_pl", "0")),
                "realizedPL": str(response.get("realized_pl", "0")),
                "time_past": float(response.get("elapsed_seconds", 0.0)),
            }
            return {"error": 0, "data": {"trade": trade}}
        trade = self.trades.get(str(trade_id))
        if trade is None:
            return {"error": 0, "data": {"trade": {"id": str(trade_id), "state": "CLOSED"}}}
        return {"error": 0, "data": {"trade": trade}}

    def TradeClose_exe(self, trade_id, units=None):
        response = self._consume_broker_response("close_trade")
        if response is not None and not bool(response.get("accepted", True)):
            return {"error": 1, "data": response}
        trade = self.trades.setdefault(
            str(trade_id),
            {
                "id": str(trade_id),
                "state": "OPEN",
                "price": "150.0",
                "currentUnits": "1000",
                "unrealizedPL": "0",
            },
        )
        trade["state"] = "CLOSED"
        trade["unrealizedPL"] = "0"
        trade["realizedPL"] = "0"
        return {"error": 0, "data": {"orderFillTransaction": {"tradeReduced": {"tradeID": str(trade_id)}}}}

    def OrderCancel_exe(self, order_id):
        response = self._consume_broker_response("cancel_order")
        if response is not None and not bool(response.get("accepted", True)):
            return {"error": 1, "data": response}
        if str(order_id) in self.orders:
            self.orders[str(order_id)]["state"] = "CANCELLED"
        return {"error": 0, "data": {"orderCancelTransaction": {"orderID": str(order_id)}}}

    def TradeCRCDO_exe(self, trade_id, data):
        self.crcdo_calls.append({"trade_id": trade_id, "data": data})
        response = self._consume_broker_response("amend_protection")
        if response is not None and not bool(response.get("accepted", True)):
            return {"error": 1, "data": response}
        return {"error": 0, "data": {"trade_id": str(trade_id)}}

    def OpenTrades_exe(self):
        return {"error": 0, "data": list(self.trades.values()), "json": {"trades": list(self.trades.values())}}

    def get_transaction_single(self, transaction_id):
        return {"error": 0, "data": {"id": str(transaction_id), "type": "ORDER_FILL"}}

    def OrderCancel_All_exe(self):
        trace = getattr(self, "trace", None)
        if trace is not None:
            trace.append("cancel_pending")
        for order in self.orders.values():
            order["state"] = "CANCELLED"
        return {"error": 0, "data": {"cancelled": list(self.orders)}}

    def TradeAllClose_exe(self):
        for trade in self.trades.values():
            trade["state"] = "CLOSED"
        return {"error": 0, "data": {"closed": list(self.trades)}}


class _LegacyCandleMetaStub:
    @staticmethod
    def cal_move_ave(_times):
        return 0


class _LegacyCandleAnalysisStub:
    def __init__(self, current_price: float = 0.0) -> None:
        self.current_price = current_price
        self.candle_meta_class = _LegacyCandleMetaStub()
        self.candle_meta_class_hour = _LegacyCandleMetaStub()
        self.peaks_class = types.SimpleNamespace(
            peaks_original=[{"latest_body_peak_price": current_price}]
        )

    candle_meta_class = _LegacyCandleMetaStub()


def _legacy_plan_summary(plan: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": plan.get("name"),
        "pair": plan.get("pair"),
        "type": plan.get("type"),
        "direction": plan.get("direction"),
        "units": plan.get("units"),
        "priority": plan.get("priority"),
        "target_price": plan.get("target_price"),
        "tp_price": plan.get("tp_price"),
        "lc_price": plan.get("lc_price"),
        "order_timeout_min": plan.get("order_timeout_min"),
        "trade_timeout_min": plan.get("trade_timeout_min"),
        "payload": (plan.get("for_api_json") or {}).get("order", {}),
    }


@contextlib.contextmanager
def _legacy_sandbox(scenario: DifferentialScenario):
    guard = _NetworkGuard()
    original_socket = socket.socket
    original_create_connection = socket.create_connection
    guard.install()

    fake_tokens = _build_tokens_stub()
    fake_notice = _build_notice_stub(fake_tokens)

    sys_modules_backup = dict(sys.modules)
    original_env = {
        "PYTHONDONTWRITEBYTECODE": os.environ.get("PYTHONDONTWRITEBYTECODE"),
        "PYTHONPATH": os.environ.get("PYTHONPATH"),
    }
    os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
    os.environ.pop("PYTHONPATH", None)

    sys.modules["tokens"] = fake_tokens
    sys.modules["send_notice"] = fake_notice

    imported = []
    try:
        import classOanda

        imported.append(classOanda)
        classOanda.Oanda = _LegacyFakeOanda

        import classCandleAnalysis
        import fLineAnalysis

        _reset_legacy_state(classCandleAnalysis, fLineAnalysis, fake_notice)

        yield _SandboxHandle(network_guard=guard, fake_notice=fake_notice)
    finally:
        guard.uninstall()
        socket.socket = original_socket
        socket.create_connection = original_create_connection
        for key, value in original_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        sys.modules.clear()
        sys.modules.update(sys_modules_backup)


def _assert_module_paths(modules: dict[str, types.ModuleType]) -> None:
    expected = os.environ.get("LEGACY_EXPECTED_WORKTREE")
    if not expected:
        return
    expected_root = Path(expected).resolve()
    for module_name, module in modules.items():
        module_file = Path(module.__file__).resolve()
        if expected_root not in module_file.parents:
            raise LegacyRunnerError(
                f"legacy module path mismatch for {module_name}: {module_file} is outside {expected_root}"
            )


class _SandboxHandle:
    def __init__(self, *, network_guard: "_NetworkGuard", fake_notice) -> None:
        self.network_guard = network_guard
        self.fake_notice = fake_notice

    def assert_no_network_calls(self) -> None:
        if self.network_guard.calls:
            raise LegacyRunnerError(f"Network call blocked: {self.network_guard.calls[0]}")


class _NetworkGuard:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self._original = None

    def install(self) -> None:
        import requests.sessions

        self._original = requests.sessions.Session.request

        def _blocked(session, method, url, *args, **kwargs):  # noqa: ANN001
            self.calls.append(f"requests:{method}:{url}")
            raise AssertionError("Network access is prohibited in legacy runner")

        requests.sessions.Session.request = _blocked

        def _blocked_socket(*args, **kwargs):  # noqa: ANN001
            self.calls.append("socket")
            raise AssertionError("Socket access is prohibited in legacy runner")

        socket.socket = _blocked_socket

        def _blocked_connection(*args, **kwargs):  # noqa: ANN001
            self.calls.append("socket.create_connection")
            raise AssertionError("Socket access is prohibited in legacy runner")

        socket.create_connection = _blocked_connection

    def uninstall(self) -> None:
        if self._original is None:
            return
        import requests.sessions

        requests.sessions.Session.request = self._original


def _build_tokens_stub() -> types.ModuleType:
    module = types.ModuleType("tokens")
    module.accountID = "test-practice-account"
    module.access_token = "test-practice-token"
    module.environment = "practice"
    module.accountIDl = "test-live-account"
    module.accountIDl2 = "test-live-account-2"
    module.access_tokenl = "test-live-token"
    module.environmentl = "practice"
    module.WEBHOOK_URL_usdyen = ""
    module.WEBHOOK_URL_eurousd = ""
    module.WEBHOOK_URL_audusd = ""
    module.WEBHOOK_URL_main = ""
    module.WEBHOOK_URL_friend = ""
    module.WEBHOOK_URL_inspection = ""
    module.folder_path = "/tmp"
    module.history_folder_path = "/tmp/"
    module.setting_json = {"l_units": 500, "hedge_close_on": False}

    def _line_send(*_args):
        return None

    module.line_send = _line_send
    return module


def _build_notice_stub(tokens_module: types.ModuleType) -> types.ModuleType:
    module = types.ModuleType("send_notice")
    module.tokens = tokens_module
    module.line_send_last_message = ""
    module.line_send_last_message_count = 0
    module.sent_messages = []

    def webhook_url_for_pair(pair):
        if pair == "AUD_USD":
            return ""
        if pair == "EUR_USD":
            return ""
        return ""

    def line_send(*args):
        module.sent_messages.append([str(item) for item in args])
        message = " ".join(str(item) for item in args)
        if module.line_send_last_message == message:
            module.line_send_last_message_count += 1
        else:
            module.line_send_last_message = message
            module.line_send_last_message_count = 1
        return 0

    module.webhook_url_for_pair = webhook_url_for_pair
    module.line_send = line_send
    return module


def _reset_legacy_state(classCandleAnalysis_module, fLineAnalysis_module, notice_module) -> None:
    candle_class = classCandleAnalysis_module.candleAnalysis
    candle_class.avoid_dup_5min_kara_time = 0
    candle_class.avoid_dup_5min_made_time = 0
    candle_class.latest_df_d5_df_r = None
    candle_class.latest_peaks_class = None
    candle_class.latest_candle_meta_class = None
    candle_class.latest_h1_df_r = None
    candle_class.latest_peaks_class_hour = None
    candle_class.latest_candle_meta_class_hour = None
    candle_class.latest_df_d30_df_r = None
    candle_class.latest_peaks_class_m30 = None
    candle_class.latest_candle_meta_class_m30 = None

    if hasattr(fLineAnalysis_module, "gl_previous_exe_df60_row"):
        fLineAnalysis_module.gl_previous_exe_df60_row = None
    if hasattr(fLineAnalysis_module, "gl_previous_exe_df60_order_time"):
        fLineAnalysis_module.gl_previous_exe_df60_order_time = None
    if hasattr(fLineAnalysis_module, "gl_previous_bb_h1_class"):
        fLineAnalysis_module.gl_previous_bb_h1_class = None
    if hasattr(fLineAnalysis_module, "gl_latest_trend_trigger_time"):
        fLineAnalysis_module.gl_latest_trend_trigger_time = None

    notice_module.line_send_last_message = ""
    notice_module.line_send_last_message_count = 0
    notice_module.sent_messages = []


def _legacy_frame_store(pair: str):
    return build_frame_store(pair)


def _legacy_generate_frame(pair: str, *, periods: int, freq: str):
    import pandas as pd

    is_jpy = pair.endswith("JPY")
    pip = 0.01 if is_jpy else 0.0001
    digits = 3 if is_jpy else 5
    base = 149.8 if is_jpy else 1.1

    times = pd.date_range(end=pd.Timestamp("2026-01-02 12:00:00"), periods=periods, freq=freq)
    rows = []
    for i, ts in enumerate(times):
        drift = ((i % 16) - 8) * pip
        close = round(base + drift, digits)
        open_price = round(close - ((i % 4) - 1) * pip, digits)
        high = round(max(open_price, close) + 2 * pip, digits)
        low = round(min(open_price, close) - 2 * pip, digits)
        inner_high = round(max(open_price, close), digits)
        inner_low = round(min(open_price, close), digits)
        body = round(close - open_price, digits)
        move = round(high - low, digits)
        rows.append(
            {
                "time_jp": ts.strftime("%Y/%m/%d %H:%M:%S"),
                "open": open_price,
                "close": close,
                "high": high,
                "low": low,
                "inner_high": inner_high,
                "inner_low": inner_low,
                "middle_price": round((inner_high + inner_low) / 2, digits),
                "middle_price_wick": round((high + low) / 2, digits),
                "mid_outer": round((high + low) / 2, digits),
                "body": body,
                "body_abs": abs(body),
                "direction": 1 if body > 0 else -1 if body < 0 else 0,
                "moves": move,
                "highlow": move,
                "up_rod": round(high - inner_high, digits),
                "low_rod": round(inner_low - low, digits),
                "RSI": float(40 + (i % 30)),
            }
        )

    frame = pd.DataFrame(rows).iloc[::-1].reset_index(drop=True)
    close_series = frame["close"]
    mean = close_series.rolling(window=30).mean()
    std = close_series.rolling(window=30).std()
    frame["bb_upper"] = mean + std * 2
    frame["bb_lower"] = mean - std * 2
    frame["bb_middle"] = ((frame["bb_lower"] + frame["bb_upper"]) / 2).round(digits)
    frame["bb_range"] = frame["bb_upper"] - frame["bb_lower"]
    return frame


def run_legacy_scenario_to_path(scenario: DifferentialScenario, output_path: Path, log_path: Path) -> None:
    result = run_legacy_scenario(scenario)
    output_tmp = output_path.with_suffix(output_path.suffix + ".tmp")
    log_tmp = log_path.with_suffix(log_path.suffix + ".tmp")
    output_tmp.write_text(json.dumps(result.trace, ensure_ascii=True), encoding="utf-8")
    log_tmp.write_text(result.log, encoding="utf-8")
    output_tmp.replace(output_path)
    log_tmp.replace(log_path)
