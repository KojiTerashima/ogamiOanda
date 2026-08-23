from __future__ import annotations

import json
import csv
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from ogami_oanda.adapters.legacy.order_dict import (
    legacy_dict_to_order_plan,
    order_plan_to_legacy_dict,
)
from ogami_oanda.adapters.oanda.mappers import (
    broker_request_to_oanda,
    map_candle_response,
    map_price_response,
)
from ogami_oanda.application.ports.market_data import MarketQuote
from ogami_oanda.application.services.line_candidate_context_builder import (
    build_line_candidate_context,
)
from ogami_oanda.application.services.market_analysis_service import (
    MarketAnalysisResult,
    MarketAnalysisService,
)
from ogami_oanda.application.services.order_planner import OrderPlanner
from ogami_oanda.application.services.position_portfolio_service import (
    PortfolioSummary,
    RegistrationResult,
    PositionPortfolioService,
)
from ogami_oanda.application.services.position_service import PositionService
from ogami_oanda.domain.market.currency_pair import currency_pair
from ogami_oanda.domain.orders.models import (
    Direction,
    OrderContext,
    OrderIntent,
    OrderType,
)
from ogami_oanda.entrypoints.live import LiveApplication
from tests.fakes import FixedClock, InMemoryTradeHistoryRepository

from .analysis_trace import (
    builtin_value,
    candidates_store_summary,
    current_intent_metadata_loss,
    current_semantic_plan,
    frame_store_summary,
    intent_summary,
    line_store_summary,
    peaks_store_summary,
    plan_summary,
    strategy_profiles_summary,
)
from .frame_factory import build_response_store
from .offline import offline_network_guard
from .scenario import DifferentialScenario
from .scripted_broker import ScriptedBroker, ScriptedStep


@dataclass(frozen=True)
class RunnerResult:
    trace: dict[str, Any]


class _ScenarioMarketData:
    def __init__(self, scenario: DifferentialScenario) -> None:
        self.scenario = scenario
        self.responses = build_response_store(
            scenario.pair,
            scenario.payload.get("frames"),
        )
        self.frames = {
            timeframe: map_candle_response(response)
            for timeframe, response in self.responses.items()
        }
        self.current_price_value = float(scenario.payload.get("current_price", 0.0) or 0.0)
        self.quote_steps = list(scenario.payload.get("live", {}).get("quote_steps", []))

    def candles(self, pair: str, granularity: str, count: int):
        if pair != self.scenario.pair:
            raise ValueError(f"pair mismatch: {pair} vs {self.scenario.pair}")
        return self.frames[granularity].head(count).copy()

    def current_price(self, pair: str) -> float:
        if pair != self.scenario.pair:
            raise ValueError(f"pair mismatch: {pair} vs {self.scenario.pair}")
        return self.current_price_value

    def current_quote(self, pair: str) -> MarketQuote:
        if pair != self.scenario.pair:
            raise ValueError(f"pair mismatch: {pair} vs {self.scenario.pair}")
        if self.quote_steps:
            step = self.quote_steps.pop(0)
            return MarketQuote(
                pair,
                float(step["bid"]),
                float(step["ask"]),
                float(step["mid"]),
            )
        mid = self.current_price(pair)
        return MarketQuote(pair, mid, mid, mid)


def run_current_scenario(scenario: DifferentialScenario) -> RunnerResult:
    with offline_network_guard():
        if scenario.kind == "analysis_order":
            return RunnerResult(trace=_run_analysis_order(scenario))
        if scenario.kind == "order_payload":
            return RunnerResult(trace=_run_order_payload(scenario))
        if scenario.kind == "position_lifecycle":
            return RunnerResult(trace=_run_position_lifecycle(scenario))
        if scenario.kind == "live_schedule":
            return RunnerResult(trace=_run_live_schedule(scenario))
        raise ValueError(f"Unsupported scenario kind: {scenario.kind}")


def _analysis_service(scenario: DifferentialScenario, market_data: _ScenarioMarketData) -> MarketAnalysisService:
    from ogami_oanda.strategy.line import LineCandidateBuilder

    return MarketAnalysisService(
        market_data,
        LineCandidateBuilder(scenario.pair),
        candidate_context_builder=build_line_candidate_context,
    )


def _run_analysis_order(scenario: DifferentialScenario) -> dict[str, Any]:
    from ogami_oanda.strategy.line import LineCandidateBuilder

    market_data = _ScenarioMarketData(scenario)
    builder = LineCandidateBuilder(scenario.pair)
    service = MarketAnalysisService(
        market_data,
        builder,
        candidate_context_builder=build_line_candidate_context,
    )
    decision_time = str(scenario.payload["decision_time"])
    current_price = float(scenario.payload["current_price"])
    analysis = service.analyze(
        scenario.pair,
        decision_time,
        current_price=current_price,
    )

    context = analysis.candidate_context
    raw_candidates = builder.build_raw_candidates(context, current_price)
    selected_by_mode = {
        mode: builder.select_candidates({mode: candidates}, context)
        for mode, candidates in raw_candidates.items()
    }
    selected_candidates = [
        candidate
        for mode in ("immediate", "future_resist", "future_break")
        for candidate in selected_by_mode[mode]
    ]
    enriched = builder.enrich_candidates(
        selected_candidates,
        current_price,
        context=context,
    )

    selected_counts = {"immediate": 0, "future_resist": 0, "future_break": 0}
    for candidate in enriched:
        mode = str(candidate.get("order_mode", "future_break"))
        if mode not in selected_counts:
            raise ValueError(f"Unsupported enriched candidate mode: {mode}")
        selected_counts[mode] += 1

    planner = OrderPlanner()
    plans = [planner.plan(intent, analysis.order_context) for intent in analysis.intents]
    legacy_plan_dicts = [order_plan_to_legacy_dict(plan) for plan in plans]
    semantic_plan_dicts = [
        current_semantic_plan(intent, legacy_plan)
        for intent, legacy_plan in zip(
            analysis.intents,
            legacy_plan_dicts,
            strict=True,
        )
    ]
    if len(enriched) != len(semantic_plan_dicts):
        raise ValueError(
            "Current enriched candidate/plan count mismatch: "
            f"{len(enriched)} != {len(semantic_plan_dicts)}"
        )
    enriched_by_mode = {
        "immediate": [],
        "future_resist": [],
        "future_break": [],
    }
    for candidate, semantic_plan in zip(
        enriched,
        semantic_plan_dicts,
        strict=True,
    ):
        mode = str(candidate.get("order_mode", "future_break"))
        enriched_by_mode[mode].append((candidate, semantic_plan))
    legacy_plans = [_legacy_plan_summary(plan) for plan in legacy_plan_dicts]

    return {
        "pair": scenario.pair,
        "kind": scenario.kind,
        "scenario_id": scenario.scenario_id,
        "events": [
            {
                "kind": "analysis",
                "decision_time": decision_time,
                "current_price": current_price,
                "raw_candidate_counts": {
                    "immediate": len(raw_candidates.get("immediate", [])),
                    "future_resist": len(raw_candidates.get("future_resist", [])),
                    "future_break": len(raw_candidates.get("future_break", [])),
                },
                "selected_candidate_counts": selected_counts,
                "frames": frame_store_summary(analysis.frames),
                "peaks": peaks_store_summary(analysis.peaks),
                "lines": line_store_summary(context),
                "candidates": candidates_store_summary(
                    raw_candidates,
                    selected_by_mode,
                    enriched_by_mode,
                ),
                "strategy_profiles": strategy_profiles_summary(raw_candidates),
                "intents": [
                    intent_summary(intent, legacy_plan=legacy_plan)
                    for intent, legacy_plan in zip(
                        analysis.intents,
                        semantic_plan_dicts,
                        strict=True,
                    )
                ],
                "intent_metadata_loss": [
                    current_intent_metadata_loss(intent, adapter_plan)
                    for intent, adapter_plan in zip(
                        analysis.intents,
                        legacy_plan_dicts,
                        strict=True,
                    )
                ],
                "plans": [plan_summary(plan) for plan in semantic_plan_dicts],
                "adapter_plans": [
                    plan_summary(plan) for plan in legacy_plan_dicts
                ],
                "payloads": [
                    dict(broker_request_to_oanda(plan.broker_request)["order"])
                    for plan in plans
                ],
                "legacy_plans": legacy_plans,
            }
        ],
    }


def _run_order_payload(scenario: DifferentialScenario) -> dict[str, Any]:
    raw_order = dict(scenario.payload["order_input"])
    raw_order.setdefault("pair", scenario.pair)
    pair = currency_pair(scenario.pair)
    order_type = OrderType(str(raw_order["type"]))
    target = float(raw_order["target"])
    take_profit = float(raw_order.get("tp", 0))
    stop_loss = float(raw_order.get("lc", 0))
    units_raw = float(raw_order.get("units", 10000))
    units = round(10000 * units_raw) if units_raw < 100 else int(round(units_raw))
    decision_time = str(raw_order["decision_time"])
    name = f"{raw_order['name']}_{decision_time[11:16]}"
    intent = OrderIntent(
        pair=scenario.pair,
        direction=Direction(int(raw_order["direction"])),
        order_type=order_type,
        target=target,
        target_is_price=pair.is_price(target),
        take_profit=take_profit,
        take_profit_is_price=pair.is_price(take_profit),
        stop_loss=stop_loss,
        stop_loss_is_price=pair.is_price(stop_loss),
        units=int(units),
        name=name,
        priority=int(raw_order.get("priority", 0)),
        order_timeout_min=int(raw_order.get("order_timeout_min", 60)),
        trade_timeout_min=int(raw_order.get("trade_timeout_min", 240)),
        lc_change=tuple(raw_order.get("lc_change", ())),
        metadata={
            "name_ymdhms": f"{raw_order['name']}_{decision_time}",
            "order_permission": bool(raw_order.get("order_permission", True)),
            "watching_price": float(raw_order.get("watching_price", 0)),
            "candle_lc_change_type": str(
                raw_order.get("candle_lc_change_type", "5M")
            ),
            "memo": str(raw_order.get("memo", "")),
        },
    )
    plan = OrderPlanner().plan(
        intent,
        OrderContext(
            current_price=float(raw_order["current_price"]),
            decision_time=decision_time,
            move_average=float(raw_order.get("move_ave", 0)),
            account_mode=int(raw_order.get("oa_mode", 2)),
        ),
    )
    legacy_plan = order_plan_to_legacy_dict(plan)
    payload = dict(broker_request_to_oanda(plan.broker_request)["order"])

    return {
        "pair": scenario.pair,
        "kind": scenario.kind,
        "scenario_id": scenario.scenario_id,
        "events": [
            {
                "kind": "order_payload",
                "plan": _legacy_plan_summary(legacy_plan),
                "payload": payload,
            }
        ],
    }


def _finalize_raw_order_like_legacy(raw_order: dict[str, Any]) -> dict[str, Any]:
    pair_name = str(raw_order.get("pair", "USD_JPY"))
    pair = currency_pair(pair_name)
    current_price = float(raw_order["current_price"])
    direction = int(raw_order["direction"])
    order_type = str(raw_order["type"])
    target_value = float(raw_order["target"])

    if pair.is_price(target_value):
        target_price = pair.round_price(target_value)
    elif order_type == "STOP":
        target_price = pair.round_price(current_price + target_value * direction)
    elif order_type == "LIMIT":
        target_price = pair.round_price(current_price - target_value * direction)
    else:
        target_price = pair.round_price(current_price)

    tp_value = float(raw_order.get("tp", 0))
    if pair.is_price(tp_value):
        tp_price = pair.round_price(tp_value)
        tp_range = pair.round_price(abs(target_price - tp_price))
    else:
        tp_range = pair.round_price(tp_value)
        tp_price = pair.round_price(target_price + tp_range * direction)

    lc_value = float(raw_order.get("lc", 0))
    if pair.is_price(lc_value):
        lc_price = pair.round_price(lc_value)
        lc_range = pair.round_price(abs(target_price - lc_price))
    else:
        lc_range = pair.round_price(lc_value)
        lc_price = pair.round_price(target_price - lc_range * direction)

    units_raw = float(raw_order.get("units", 10000))
    units = round(10000 * units_raw) if units_raw < 100 else int(round(units_raw))

    decision_time = str(raw_order["decision_time"])
    base_name = str(raw_order["name"])
    short_time = decision_time[11:16]

    return {
        "decision_time": decision_time,
        "current_price": current_price,
        "units": int(units),
        "pair": pair_name,
        "direction": direction,
        "target_price": target_price,
        "lc_price": lc_price,
        "lc_range": lc_range,
        "tp_price": tp_price,
        "tp_range": tp_range,
        "type": order_type,
        "name": f"{base_name}_{short_time}",
        "name_ymdhms": f"{base_name}_{decision_time}",
        "oa_mode": int(raw_order.get("oa_mode", 2)),
        "order_timeout_min": int(raw_order.get("order_timeout_min", 60)),
        "trade_timeout_min": int(raw_order.get("trade_timeout_min", 240)),
        "order_permission": bool(raw_order.get("order_permission", True)),
        "priority": int(raw_order.get("priority", 0)),
        "watching_price": float(raw_order.get("watching_price", 0)),
        "lc_price_original": lc_price,
        "tp_price_original": tp_price,
        "lc_change": list(raw_order.get("lc_change", [])),
        "move_ave": float(raw_order.get("move_ave", 0)),
        "candle_lc_change_type": str(raw_order.get("candle_lc_change_type", "5M")),
        "memo": str(raw_order.get("memo", "")),
    }


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


def _scripted_broker_for_scenario(scenario: DifferentialScenario) -> ScriptedBroker:
    script = scenario.payload.get("broker_script", {})

    def _steps(name: str) -> list[ScriptedStep]:
        values = script.get(name, [])
        return [
            ScriptedStep(
                action=name,
                accepted=bool(item.get("accepted", True)),
                reference_id=item.get("reference_id"),
                message=str(item.get("message", "")),
                exception=(
                    str(item["exception"])
                    if item.get("exception") is not None
                    else None
                ),
            )
            for item in values
        ]

    return ScriptedBroker(
        submit_steps=_steps("submit"),
        cancel_steps=_steps("cancel_order"),
        close_steps=_steps("close_trade"),
        amend_steps=_steps("amend_protection"),
        raw_steps=scenario.payload.get("broker_steps"),
    )


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

    broker = _scripted_broker_for_scenario(scenario)
    decision_time = datetime.fromisoformat(str(scenario.payload["decision_time"]))
    clock = FixedClock(decision_time)
    history = InMemoryTradeHistoryRepository()

    position_service = PositionService(
        broker,
        broker,
        _MemoryNotifier(),
        history,
        clock,
    )
    portfolio = PositionPortfolioService(scenario.pair, position_service, broker, broker)

    raw_orders = list(scenario.payload["position"].get("orders", []))
    plans = [
        legacy_dict_to_order_plan(
            _finalize_raw_order_like_legacy(dict(raw_order)),
            current_price=float(raw_order["current_price"]),
        )
        for raw_order in raw_orders
    ]
    registration = portfolio.register_plans(plans, submit=bool(scenario.payload["position"].get("submit", False)))

    sync_result = portfolio.sync_all(
        current_price=float(raw_orders[0]["current_price"]) if raw_orders else float(scenario.payload["position"].get("current_price", 0)),
        dry_run=bool(scenario.payload["position"].get("dry_run", True)),
    )

    return {
        "pair": scenario.pair,
        "kind": scenario.kind,
        "scenario_id": scenario.scenario_id,
        "events": [
            {
                "kind": "position_lifecycle",
                "registration": {
                    "accepted_count": len(registration.accepted),
                    "rejected_count": len(registration.rejected),
                    "raw_result": None,
                },
                "counts": {
                    "watching": sync_result.watching,
                    "pending": sync_result.pending,
                    "open": sync_result.open,
                    "life_exist": bool(sync_result.watching or sync_result.pending or sync_result.open),
                },
            },
        ],
    }


def _run_position_watching(scenario: DifferentialScenario) -> dict[str, Any]:
    position_spec = scenario.payload["position"]
    raw_order = dict(position_spec["order"])
    raw_order.setdefault("pair", scenario.pair)
    raw_order.setdefault("decision_time", scenario.payload["decision_time"])
    raw_order.setdefault("order_permission", False)
    finalized = _finalize_raw_order_like_legacy(raw_order)
    plan = legacy_dict_to_order_plan(
        finalized,
        current_price=float(raw_order["current_price"]),
    )
    first_at = datetime.fromisoformat(str(position_spec["ticks"][0]["at"]))
    clock = FixedClock(first_at)
    broker = _scripted_broker_for_scenario(scenario)
    position_service = PositionService(
        broker,
        broker,
        _MemoryNotifier(),
        InMemoryTradeHistoryRepository(),
        clock,
    )
    portfolio = PositionPortfolioService(
        scenario.pair,
        position_service,
        broker,
        broker,
    )
    portfolio.register_plans([plan], submit=False)

    events = []
    for tick in position_spec["ticks"]:
        clock.value = datetime.fromisoformat(str(tick["at"]))
        summary = portfolio.sync_all(current_price=float(tick["price"]))
        position = next((item for item in portfolio.slots if item is not None), None)
        events.append(
            {
                "kind": "position_tick",
                "at": clock.value.isoformat(),
                "price": float(tick["price"]),
                "slot": _current_watching_slot(position),
                "commands": [
                    {"action": command.action}
                    for command in summary.commands
                ],
                "events": [event.kind for event in summary.events],
            }
        )

    return {
        "pair": scenario.pair,
        "kind": scenario.kind,
        "scenario_id": scenario.scenario_id,
        "events": events,
    }


def _current_watching_slot(position) -> dict[str, Any]:
    if position is None:
        return {
            "name": None,
            "life": False,
            "waiting_order": False,
            "order_state": "EMPTY",
            "trade_state": "NONE",
            "step1_started_at": None,
            "step2_started_at": None,
        }
    return {
        "name": position.snapshot.name,
        "life": bool(position.snapshot.life),
        "waiting_order": bool(position.snapshot.waiting_order),
        "order_state": position.snapshot.order_state.value,
        "trade_state": position.snapshot.trade_state.value,
        "step1_started_at": (
            position.runtime.watch_step1_started_at.isoformat()
            if position.runtime.watch_step1_started_at
            else None
        ),
        "step2_started_at": (
            position.runtime.watch_step2_started_at.isoformat()
            if position.runtime.watch_step2_started_at
            else None
        ),
    }


def _position_service_for_ticks(scenario, first_at):
    clock = FixedClock(first_at)
    broker = _scripted_broker_for_scenario(scenario)
    service = PositionService(
        broker,
        broker,
        _MemoryNotifier(),
        InMemoryTradeHistoryRepository(),
        clock,
    )
    return service, broker, clock


def _position_plan_from_scenario(scenario):
    raw_order = dict(scenario.payload["position"]["order"])
    raw_order.setdefault("pair", scenario.pair)
    raw_order.setdefault("decision_time", scenario.payload["decision_time"])
    finalized = _finalize_raw_order_like_legacy(raw_order)
    return legacy_dict_to_order_plan(
        finalized,
        current_price=float(raw_order["current_price"]),
    )


def _run_position_pending_timeout(scenario: DifferentialScenario) -> dict[str, Any]:
    from ogami_oanda.domain.positions.managed_position import ManagedPosition
    from ogami_oanda.domain.positions.models import OrderState, PositionSnapshot, TradeState

    spec = scenario.payload["position"]
    first_at = datetime.fromisoformat(str(spec["ticks"][0]["at"]))
    service, broker, clock = _position_service_for_ticks(scenario, first_at)
    plan = _position_plan_from_scenario(scenario)
    position = (
        ManagedPosition.registered(plan.intent.name, scenario.pair)
        .with_order_plan(plan, first_at)
        .pending("order-1")
    )
    broker.orders["order-1"] = PositionSnapshot(
        plan.intent.name,
        scenario.pair,
        OrderState.PENDING,
        TradeState.NONE,
        order_id="order-1",
        life=True,
    )
    events = []
    for tick in spec["ticks"]:
        clock.value = datetime.fromisoformat(str(tick["at"]))
        action_offset = len(broker.broker_actions)
        result = service.sync_result(position, current_price=float(tick["price"]))
        position = result.position
        events.append(
            {
                "kind": "position_tick",
                "at": clock.value.isoformat(),
                "price": float(tick["price"]),
                "slot": {
                    "name": position.snapshot.name,
                    "life": bool(position.snapshot.life),
                    "order_state": position.snapshot.order_state.value,
                    "trade_state": position.snapshot.trade_state.value,
                },
                "commands": [
                    {"action": command.action}
                    for command in result.commands
                ],
                "events": [event.kind for event in result.events],
                "broker_actions": broker.broker_actions[action_offset:],
            }
        )
    broker.assert_broker_steps_consumed()
    return {
        "pair": scenario.pair,
        "kind": scenario.kind,
        "scenario_id": scenario.scenario_id,
        "events": events,
    }


def _run_position_lc_change(scenario: DifferentialScenario) -> dict[str, Any]:
    from dataclasses import replace

    from ogami_oanda.domain.positions.managed_position import ManagedPosition
    from ogami_oanda.domain.positions.models import OrderState, PositionSnapshot, TradeState

    spec = scenario.payload["position"]
    first_at = datetime.fromisoformat(str(spec["ticks"][0]["at"]))
    service, broker, clock = _position_service_for_ticks(scenario, first_at)
    plan = _position_plan_from_scenario(scenario)
    position = (
        ManagedPosition.registered(plan.intent.name, scenario.pair)
        .with_order_plan(plan, first_at)
        .filled("trade-1", first_at)
    )
    broker.trades["trade-1"] = PositionSnapshot(
        plan.intent.name,
        scenario.pair,
        OrderState.FILLED,
        TradeState.OPEN,
        trade_id="trade-1",
        life=True,
        direction=plan.intent.direction.value,
        target_price=plan.target_price,
        current_stop_loss=plan.stop_loss_price,
    )
    events = []
    for tick in spec["ticks"]:
        clock.value = datetime.fromisoformat(str(tick["at"]))
        result = service.sync_result(position, current_price=float(tick["price"]))
        position = result.position
        for command in result.commands:
            if command.action == "amend_stop_loss":
                broker.trades["trade-1"] = replace(
                    broker.trades["trade-1"],
                    current_stop_loss=command.stop_loss_price,
                )
        events.append(
            {
                "kind": "position_tick",
                "at": clock.value.isoformat(),
                "price": float(tick["price"]),
                "slot": {
                    "name": position.snapshot.name,
                    "life": bool(position.snapshot.life),
                    "order_state": position.snapshot.order_state.value,
                    "trade_state": position.snapshot.trade_state.value,
                    "current_stop_loss": position.runtime.current_stop_loss,
                    "applied_rule_count": (
                        position.runtime.applied_lc_change_index + 1
                        if position.runtime.applied_lc_change_index >= 0
                        else 0
                    ),
                },
                "commands": [
                    {
                        "action": command.action,
                        "stop_loss_price": command.stop_loss_price,
                    }
                    for command in result.commands
                ],
                "events": [event.kind for event in result.events],
            }
        )
    return {
        "pair": scenario.pair,
        "kind": scenario.kind,
        "scenario_id": scenario.scenario_id,
        "events": events,
    }


def _run_portfolio_acceptance(scenario: DifferentialScenario) -> dict[str, Any]:
    first_at = datetime.fromisoformat(
        str(scenario.payload["decision_time"]).replace("/", "-")
    )
    service, broker, _clock = _position_service_for_ticks(scenario, first_at)
    portfolio = PositionPortfolioService(
        scenario.pair,
        service,
        broker,
        broker,
    )
    events = []
    for batch_index, batch in enumerate(scenario.payload["position"]["batches"]):
        plans = []
        for raw in batch:
            order = dict(raw)
            order.setdefault("pair", scenario.pair)
            order.setdefault("decision_time", scenario.payload["decision_time"])
            order.setdefault("order_permission", False)
            order.setdefault("lc_change", [])
            plans.append(
                legacy_dict_to_order_plan(
                    _finalize_raw_order_like_legacy(order),
                    current_price=float(order["current_price"]),
                )
            )
        registration = portfolio.register_plans(plans, submit=False)
        events.append(
            {
                "kind": "portfolio_batch",
                "batch_index": batch_index,
                "accepted": list(registration.accepted),
                "rejected": [
                    {"name": name, "reason": reason}
                    for name, reason in registration.rejected
                ],
                "slots": [
                    {
                        "index": index,
                        "name": position.snapshot.name,
                        "priority": int(position.runtime.order_plan.intent.priority),
                    }
                    for index, position in enumerate(portfolio.slots)
                    if position is not None
                ],
            }
        )
    return {
        "pair": scenario.pair,
        "kind": scenario.kind,
        "scenario_id": scenario.scenario_id,
        "events": events,
    }


def _run_broker_outcome(scenario: DifferentialScenario) -> dict[str, Any]:
    from ogami_oanda.domain.positions.managed_position import ManagedPosition

    spec = scenario.payload["position"]
    outcome = str(spec["outcome"])
    first_at = datetime.fromisoformat(
        str(scenario.payload["decision_time"]).replace("/", "-")
    )
    broker = _scripted_broker_for_scenario(scenario)
    clock = FixedClock(first_at)
    service = PositionService(
        broker,
        broker,
        _MemoryNotifier(),
        InMemoryTradeHistoryRepository(),
        clock,
    )
    plan = _position_plan_from_scenario(scenario)
    error: str | None = None
    query_events = []
    try:
        position = service.register(
            ManagedPosition.registered(plan.intent.name, scenario.pair),
            plan,
            submit=True,
        )
        accepted = bool(position.snapshot.life)
        if outcome == "not_found":
            for attempt in range(1, int(spec.get("query_attempts", 4)) + 1):
                result = service.sync_result(position)
                position = result.position
                query_events.append(
                    {
                        "attempt": attempt,
                        "life": bool(position.snapshot.life),
                        "order_state": position.snapshot.order_state.value,
                        "reason": result.reason,
                    }
                )
    except RuntimeError as caught:
        position = ManagedPosition.registered(plan.intent.name, scenario.pair)
        accepted = False
        error = str(caught)

    event = {
        "kind": "broker_outcome",
        "outcome": outcome,
        "accepted": accepted,
        "life": bool(position.snapshot.life),
        "order_state": (
            "ERROR" if error else position.snapshot.order_state.value
        ),
        "submit_count": len(broker.requests),
        "error": error,
        "queries": query_events,
        "broker_actions": list(broker.broker_actions),
    }
    broker.assert_broker_steps_consumed()
    return {
        "pair": scenario.pair,
        "kind": scenario.kind,
        "scenario_id": scenario.scenario_id,
        "events": [event],
    }


def _run_linkage_hedge(scenario: DifferentialScenario) -> dict[str, Any]:
    from ogami_oanda.domain.positions.models import OrderState, TradeState
    from ogami_oanda.strategy.position_management import (
        HedgePolicy,
        HedgePosition,
        LinkagePolicy,
        LinkedPosition,
    )

    events = []
    linkage = LinkagePolicy()
    for check in scenario.payload["position"]["checks"]:
        if check == "pending_cancel":
            commands = linkage.on_main_filled(
                [
                    LinkedPosition(
                        "linked-pending",
                        -1,
                        150.0,
                        0.05,
                        150.2,
                        OrderState.PENDING,
                        TradeState.NONE,
                        True,
                    )
                ]
            )
        elif check == "loss_lc":
            commands = linkage.on_main_closed(
                main_direction=1,
                main_price_diff=-0.03,
                linked_positions=[
                    LinkedPosition(
                        "linked-open",
                        -1,
                        150.0,
                        0.05,
                        150.2,
                        OrderState.FILLED,
                        TradeState.OPEN,
                        True,
                    )
                ],
            )
        elif check == "hedge_noop":
            commands = HedgePolicy().close_commands(
                [
                    HedgePosition("long", 1, 0.3),
                    HedgePosition("short", -1, 0.3),
                ]
            )
        else:
            raise ValueError(f"Unsupported linkage/hedge check: {check}")
        events.append(
            {
                "kind": "position_policy",
                "check": check,
                "commands": [
                    {
                        "action": command.action,
                        "position_id": command.position_id,
                        **(
                            {"stop_loss_price": command.stop_loss_price}
                            if getattr(command, "stop_loss_price", None) is not None
                            else {}
                        ),
                    }
                    for command in commands
                ],
            }
        )
    return {
        "pair": scenario.pair,
        "kind": scenario.kind,
        "scenario_id": scenario.scenario_id,
        "events": events,
    }


def _run_close_reporting(scenario: DifferentialScenario) -> dict[str, Any]:
    from ogami_oanda.adapters.repositories.csv_trade_history import (
        CsvTradeHistoryRepository,
    )
    from ogami_oanda.domain.positions.managed_position import ManagedPosition
    from ogami_oanda.domain.positions.models import OrderState, PositionSnapshot, TradeState

    spec = scenario.payload["position"]
    first_at = datetime.fromisoformat(
        str(scenario.payload["decision_time"]).replace("/", "-")
    )
    broker = _scripted_broker_for_scenario(scenario)
    notifier = _MemoryNotifier()
    history_file = tempfile.NamedTemporaryFile(
        prefix="ogami-current-differential-history-",
        suffix=".csv",
        delete=False,
    )
    history_path = Path(history_file.name)
    history_file.close()
    history_path.unlink(missing_ok=True)
    history = CsvTradeHistoryRepository(history_path)
    clock = FixedClock(first_at)
    service = PositionService(broker, broker, notifier, history, clock)
    raw_order = {
        "name": str(spec["name"]),
        "current_price": float(spec["target_price"]),
        "target": float(spec["target_price"]),
        "direction": int(spec.get("direction", 1)),
        "type": "LIMIT",
        "tp": float(spec.get("tp_price", 150.25)),
        "lc": float(spec.get("lc_price", 149.95)),
        "lc_change": [],
        "units": int(spec["units"]),
        "priority": 1,
        "decision_time": scenario.payload["decision_time"],
        "pair": scenario.pair,
        "memo": str(spec.get("memo", "close memo")),
        "move_ave": 0.05,
    }
    finalized = _finalize_raw_order_like_legacy(raw_order)
    finalized.update(
        {
            "name": str(spec["name"]),
            "name_ymdhms": str(spec.get("name_ymdhms", spec["name"])),
            "lc_price_original": float(spec.get("lc_price_original", 149.9)),
            "tp_price_original": float(spec.get("tp_price_original", 150.3)),
            "move_ave60": 0.15,
            "current_price_gap": 0.02,
            "gap_target_price_pips": 3.5,
            "lc_change_str": "(3p-1p)",
            "max_plus_pips": 12,
            "max_minus_pips": -4,
        }
    )
    plan = legacy_dict_to_order_plan(
        finalized,
        current_price=float(spec["target_price"]),
    )
    position = (
        ManagedPosition.registered(str(spec["name"]), scenario.pair)
        .with_order_plan(plan, datetime(2026, 1, 2, 9, 0, 0))
        .pending(str(spec["order_id"]))
        .filled(
            str(spec["trade_id"]),
            datetime(2026, 1, 2, 9, 10, 0),
            order_id=str(spec["order_id"]),
        )
        .with_runtime(
            current_stop_loss=float(spec.get("lc_price", 149.95)),
            max_unrealized_pl=1200,
            min_unrealized_pl=-400,
        )
    )
    broker.trades[str(spec["trade_id"])] = PositionSnapshot(
        str(spec["name"]),
        scenario.pair,
        OrderState.FILLED,
        TradeState.CLOSED,
        order_id=str(spec["order_id"]),
        trade_id=str(spec["trade_id"]),
        life=False,
        direction=int(spec.get("direction", 1)),
        target_price=float(spec["target_price"]),
        units=int(spec["units"]),
        realized_pl=float(spec["realized_pl"]),
        average_close_price=float(spec["close_price"]),
        open_time="2026/01/02 09:10:00",
        close_time="2026/01/02 09:20:00",
        elapsed_seconds=600,
    )
    first = service.sync_result(position)
    second = service.sync_result(position)
    try:
        with history_path.open(newline="", encoding="utf-8") as stream:
            reader = csv.DictReader(stream)
            csv_rows = list(reader)
            csv_columns = list(reader.fieldnames or ())
    finally:
        history_path.unlink(missing_ok=True)
    analytics = service.closure_reporting.analytics
    event = {
        "kind": "close_reporting",
        "close_event_count": len(first.events) + len(second.events),
        "history": {
            "columns": csv_columns,
            "rows": [
                [builtin_value(row[column]) for column in csv_columns]
                for row in csv_rows
            ],
        },
        "notifications": [message for message, _category, _pair in notifier.messages],
        "analytics": {
            "total_yen": analytics.total_yen,
            "total_pips": analytics.total_pips,
            "plus_count": analytics.plus_yen_position_num,
            "minus_count": analytics.minus_yen_position_num,
            "latest_name": analytics.before_latest_name,
        },
    }
    return {
        "pair": scenario.pair,
        "kind": scenario.kind,
        "scenario_id": scenario.scenario_id,
        "events": [event],
    }


def _run_trade_timeout_disabled(scenario: DifferentialScenario) -> dict[str, Any]:
    from ogami_oanda.domain.positions.managed_position import ManagedPosition
    from ogami_oanda.domain.positions.models import OrderState, PositionSnapshot, TradeState

    spec = scenario.payload["position"]
    first_at = datetime.fromisoformat(str(spec["ticks"][0]["at"]))
    service, broker, clock = _position_service_for_ticks(scenario, first_at)
    plan = _position_plan_from_scenario(scenario)
    position = (
        ManagedPosition.registered(plan.intent.name, scenario.pair)
        .with_order_plan(plan, first_at)
        .filled("trade-timeout", first_at)
    )
    broker.trades["trade-timeout"] = PositionSnapshot(
        plan.intent.name,
        scenario.pair,
        OrderState.FILLED,
        TradeState.OPEN,
        trade_id="trade-timeout",
        life=True,
        direction=plan.intent.direction.value,
        target_price=plan.target_price,
        current_stop_loss=plan.stop_loss_price,
    )
    events = []
    for tick in spec["ticks"]:
        clock.value = datetime.fromisoformat(str(tick["at"]))
        result = service.sync_result(
            position,
            current_price=float(tick["price"]),
        )
        position = result.position
        events.append(
            {
                "kind": "position_tick",
                "elapsed_seconds": int(tick["elapsed_seconds"]),
                "commands": [
                    {"action": command.action}
                    for command in result.commands
                ],
                "slot": {
                    "life": bool(position.snapshot.life),
                    "trade_state": position.snapshot.trade_state.value,
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
    from dataclasses import replace

    from ogami_oanda.application.services.position_service import CandleStopLossInput
    from ogami_oanda.domain.positions.managed_position import ManagedPosition
    from ogami_oanda.domain.positions.models import OrderState, PositionSnapshot, TradeState

    spec = scenario.payload["position"]
    first_tick = datetime.fromisoformat(str(spec["ticks"][0]["at"]))
    filled_at = datetime.fromisoformat(
        str(scenario.payload["decision_time"]).replace("/", "-")
    )
    service, broker, clock = _position_service_for_ticks(scenario, first_tick)
    plan = _position_plan_from_scenario(scenario)
    position = (
        ManagedPosition.registered(plan.intent.name, scenario.pair)
        .with_order_plan(plan, filled_at)
        .filled("trade-candle", filled_at)
    )
    broker.trades["trade-candle"] = PositionSnapshot(
        plan.intent.name,
        scenario.pair,
        OrderState.FILLED,
        TradeState.OPEN,
        trade_id="trade-candle",
        life=True,
        direction=plan.intent.direction.value,
        target_price=plan.target_price,
        current_stop_loss=plan.stop_loss_price,
    )
    candle_input = CandleStopLossInput(
        latest_peak=dict(spec["latest_peak"]),
        previous_candle=dict(spec["previous_candle"]),
    )
    events = []
    for tick in spec["ticks"]:
        clock.value = datetime.fromisoformat(str(tick["at"]))
        result = service.sync_result(
            position,
            current_price=float(tick["price"]),
            candle_stop_loss=candle_input,
        )
        position = result.position
        for command in result.commands:
            if command.action == "amend_stop_loss":
                broker.trades["trade-candle"] = replace(
                    broker.trades["trade-candle"],
                    current_stop_loss=command.stop_loss_price,
                )
        events.append(
            {
                "kind": "position_tick",
                "elapsed_seconds": int(tick["elapsed_seconds"]),
                "commands": [
                    {
                        "action": command.action,
                        "stop_loss_price": command.stop_loss_price,
                    }
                    for command in result.commands
                ],
                "slot": {
                    "current_stop_loss": position.runtime.current_stop_loss,
                    "candle_lc_done": bool(position.runtime.candle_stop_loss_done),
                },
            }
        )
    return {
        "pair": scenario.pair,
        "kind": scenario.kind,
        "scenario_id": scenario.scenario_id,
        "events": events,
    }


def _run_restore(scenario: DifferentialScenario) -> dict[str, Any]:
    from ogami_oanda.domain.positions.managed_position import ManagedPosition
    from ogami_oanda.domain.positions.models import OrderState, PositionSnapshot, TradeState

    spec = scenario.payload["position"]
    first_at = datetime.fromisoformat(
        str(scenario.payload["decision_time"]).replace("/", "-")
    )
    service, broker, _clock = _position_service_for_ticks(scenario, first_at)
    portfolio = PositionPortfolioService(
        scenario.pair,
        service,
        broker,
        broker,
    )
    initial_slots = spec["initial_slots"]
    for index, initial in enumerate(initial_slots):
        if initial is None:
            continue
        portfolio.slots[index] = ManagedPosition.registered(
            str(initial["name"]),
            scenario.pair,
        ).watching()
    occupied = sum(item is not None for item in initial_slots)
    pair_index = 0
    for item in spec["broker_positions"]:
        trade_id = str(item["id"])
        direction = 1 if int(item["currentUnits"]) > 0 else -1
        if str(item["instrument"]) != scenario.pair:
            name = str(item.get("name", f"restored-{trade_id}"))
        else:
            name = f"既存{pair_index}_10:00"
            pair_index += 1
        broker.positions[trade_id] = PositionSnapshot(
            name,
            str(item["instrument"]),
            OrderState.FILLED,
            TradeState.OPEN,
            trade_id=trade_id,
            life=True,
            direction=direction,
            target_price=float(item["price"]),
            current_stop_loss=(
                float(item["stopLossOrder"]["price"])
                if item.get("stopLossOrder")
                else None
            ),
        )
    portfolio.restore_open_positions()
    slots = [
        {
            "index": index,
            "name": position.snapshot.name,
            "trade_id": str(position.snapshot.trade_id),
            "direction": int(position.runtime.direction),
            "target_price": float(position.runtime.target_price),
        }
        for index, position in enumerate(portfolio.slots)
        if position is not None and index >= occupied
    ]
    return {
        "pair": scenario.pair,
        "kind": scenario.kind,
        "scenario_id": scenario.scenario_id,
        "events": [{"kind": "restore", "slots": slots}],
    }


def _run_active_dedup(scenario: DifferentialScenario) -> dict[str, Any]:
    from ogami_oanda.application.services.portfolio import ActiveOrder, Portfolio
    from ogami_oanda.domain.market.currency_pair import currency_pair

    spec = scenario.payload["position"]
    active = tuple(
        ActiveOrder(
            str(item["name"]),
            int(item["direction"]),
            float(item["target_price"]),
            item.get("source"),
            item.get("line_strategy"),
        )
        for item in spec["active"]
    )
    candidate = spec["candidate"]
    portfolio = Portfolio(currency_pair(scenario.pair), active)
    is_exist = portfolio.has_similar_active_order(
        int(candidate["direction"]),
        float(candidate["target_price"]),
        threshold_pips=int(candidate.get("threshold_pips", 3)),
        source=candidate.get("source"),
        line_strategy=candidate.get("line_strategy"),
    )
    matching = next(
        (
            item
            for item in active
            if item.source == candidate.get("source")
            and item.line_strategy == candidate.get("line_strategy")
            and item.direction == int(candidate["direction"])
            and abs(
                currency_pair(scenario.pair).price_to_pips(
                    item.target_price - float(candidate["target_price"])
                )
            )
            <= int(candidate.get("threshold_pips", 3))
        ),
        None,
    )
    event = {
        "kind": "active_dedup",
        "is_exist": bool(is_exist),
        "name": matching.name if matching else None,
        "gap_pips": (
            abs(
                currency_pair(scenario.pair).price_to_pips(
                    matching.target_price - float(candidate["target_price"])
                )
            )
            if matching
            else None
        ),
        "source": matching.source if matching else None,
        "line_strategy": matching.line_strategy if matching else None,
    }
    return {
        "pair": scenario.pair,
        "kind": scenario.kind,
        "scenario_id": scenario.scenario_id,
        "events": [event],
    }


def _run_live_schedule(scenario: DifferentialScenario) -> dict[str, Any]:
    from ogami_oanda.domain.orders.models import (
        Direction,
        OrderContext,
        OrderIntent,
        OrderType,
    )
    from ogami_oanda.domain.positions.models import OrderState, PositionSnapshot, TradeState

    live = scenario.payload["live"]
    first_tick = live["ticks"][0]
    clock = FixedClock(datetime.fromisoformat(str(first_tick["now"])))
    call_sequence: list[str] = []

    class _LiveMarket:
        def __init__(self) -> None:
            self.tick = first_tick
            self.last_quote: dict[str, object] | None = None
            self.consumed = 0

        def current_quote(self, pair: str) -> MarketQuote:
            call_sequence.append("quote")
            if self.consumed:
                raise ValueError("Live tick price_response was consumed more than once")
            mapped = map_price_response(pair, self.tick["price_response"])
            self.last_quote = mapped
            self.consumed += 1
            return MarketQuote(
                pair,
                float(mapped["bid"]),
                float(mapped["ask"]),
                float(mapped["mid"]),
                bool(mapped["tradeable"]),
            )

    class _LiveAnalysis:
        def analyze(self, pair, decision_time, *, current_price=None):
            call_sequence.append("analysis")
            intents = tuple(
                OrderIntent(
                    pair=pair,
                    direction=Direction.BUY,
                    order_type=OrderType.LIMIT,
                    target=float(current_price),
                    target_is_price=True,
                    take_profit=0.1,
                    take_profit_is_price=False,
                    stop_loss=0.1,
                    stop_loss_is_price=False,
                    units=1000,
                    name=f"live-candidate-{index}",
                    priority=1,
                    order_timeout_min=30,
                )
                for index in range(int(live.get("candidate_count", 0)))
            )
            return MarketAnalysisResult(
                intents,
                {},
                {},
                OrderContext(float(current_price), str(decision_time)),
            )

    class _LivePortfolio:
        def sync_all(self, **_kwargs):
            call_sequence.append("sync")
            return PortfolioSummary(0, 0, 0, 0)

        def register_plans(self, plans, submit=True):
            del submit
            call_sequence.append("register")
            return RegistrationResult(
                tuple(plan.intent.name for plan in plans),
                (),
            )

    market_data = _LiveMarket()
    app = LiveApplication(
        scenario.pair,
        market_data,
        _LiveAnalysis(),
        OrderPlanner(),
        _LivePortfolio(),
        clock,
    )
    if live.get("first_exe") is False:
        latest = live.get("latest_exe_time")
        app._last_analysis_at = (
            datetime.fromisoformat(str(latest))
            if latest
            else clock.now()
        )

    events = []
    startup_orders = list(live.get("startup_pending_orders", ()))
    if startup_orders and live.get("cancel_pending_on_start", False):
        startup_broker = _scripted_broker_for_scenario(scenario)
        for item in startup_orders:
            order_id = str(item["order_id"])
            startup_broker.orders[order_id] = PositionSnapshot(
                str(item.get("name", order_id)),
                scenario.pair,
                OrderState.PENDING,
                TradeState.NONE,
                order_id=order_id,
                life=True,
            )
        startup_service = PositionService(
            startup_broker,
            startup_broker,
            _MemoryNotifier(),
            InMemoryTradeHistoryRepository(),
            clock,
        )
        startup_portfolio = PositionPortfolioService(
            scenario.pair,
            startup_service,
            startup_broker,
            startup_broker,
        )
        cancelled = startup_portfolio.cancel_pending_on_start(True)
        events.append(
            {
                "kind": "live_startup",
                "sequence": ["cancel_pending"],
                "cancelled_order_ids": sorted(cancelled),
            }
        )
    for tick in live["ticks"]:
        now = datetime.fromisoformat(str(tick["now"]))
        clock.value = now
        market_data.tick = tick
        market_data.last_quote = None
        market_data.consumed = 0
        call_sequence.clear()
        result = app.run_once(
            now=now,
            dry_run=bool(live.get("dry_run", True)),
            decision_time=tick.get("decision_time", live.get("decision_time")),
        )
        if "market_closed" in result.skipped:
            decision = "market_closed"
        elif result.analysis is not None:
            decision = "analyze"
        elif "update_only" in result.skipped:
            decision = "update_only"
        else:
            decision = "idle"
        events.append(
            {
                "kind": "live_tick",
                "now": now.isoformat(),
                "decision": decision,
                "sequence": list(call_sequence),
                "quote_count": call_sequence.count("quote"),
                "quote": (
                    dict(market_data.last_quote)
                    if result.quote is not None
                    else None
                ),
                "plan_count": len(result.plans),
                "accepted_count": len(result.registration.accepted),
                "rejected_count": len(result.registration.rejected),
            }
        )

    return {
        "pair": scenario.pair,
        "kind": scenario.kind,
        "scenario_id": scenario.scenario_id,
        "events": events,
    }


class _MemoryNotifier:
    def __init__(self) -> None:
        self.messages: list[tuple[str, str, str | None]] = []

    def send(self, message: str, *, category: str = "live", pair: str | None = None) -> None:
        self.messages.append((message, category, pair))


def run_current_scenario_to_path(scenario: DifferentialScenario, output_path: Path) -> None:
    result = run_current_scenario(scenario)
    tmp = output_path.with_suffix(output_path.suffix + ".tmp")
    tmp.write_text(json.dumps(result.trace, ensure_ascii=True), encoding="utf-8")
    tmp.replace(output_path)
