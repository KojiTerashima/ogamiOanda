from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from ogami_oanda.adapters.legacy.order_dict import (
    legacy_dict_to_order_plan,
    order_plan_to_legacy_dict,
)
from ogami_oanda.application.ports.market_data import MarketQuote
from ogami_oanda.application.services.line_candidate_context_builder import (
    build_line_candidate_context,
)
from ogami_oanda.application.services.market_analysis_service import (
    MarketAnalysisService,
)
from ogami_oanda.application.services.order_planner import OrderPlanner
from ogami_oanda.application.services.position_portfolio_service import (
    PositionPortfolioService,
)
from ogami_oanda.application.services.position_service import PositionService
from ogami_oanda.domain.market.currency_pair import currency_pair
from ogami_oanda.entrypoints.live import LiveApplication
from tests.fakes import FixedClock, InMemoryTradeHistoryRepository

from .frame_factory import build_legacy_parity_frame_store
from .scenario import DifferentialScenario
from .scripted_broker import ScriptedBroker, ScriptedStep


@dataclass(frozen=True)
class RunnerResult:
    trace: dict[str, Any]


class _ScenarioMarketData:
    def __init__(self, scenario: DifferentialScenario) -> None:
        self.scenario = scenario
        self.frames = build_legacy_parity_frame_store(scenario.pair)
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
    selected_candidates = builder.select_candidates(raw_candidates, context)
    enriched = builder.enrich_candidates(selected_candidates, current_price)

    selected_counts = {"immediate": 0, "future_resist": 0, "future_break": 0}
    for candidate in enriched:
        mode = str(candidate.get("order_mode", "future_break"))
        if mode in selected_counts:
            selected_counts[mode] += 1

    planner = OrderPlanner()
    plans = [planner.plan(intent, analysis.order_context) for intent in analysis.intents]
    legacy_plans = [_legacy_plan_summary(order_plan_to_legacy_dict(plan)) for plan in plans]

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
                "legacy_plans": legacy_plans,
            }
        ],
    }


def _run_order_payload(scenario: DifferentialScenario) -> dict[str, Any]:
    raw_order = dict(scenario.payload["order_input"])
    raw_order.setdefault("pair", scenario.pair)
    finalized = _finalize_raw_order_like_legacy(raw_order)
    plan = legacy_dict_to_order_plan(
        finalized,
        current_price=float(finalized.get("current_price", 0.0) or 0.0),
    )
    legacy_plan = order_plan_to_legacy_dict(plan)
    payload = dict((legacy_plan.get("for_api_json") or {}).get("order", {}))

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
            )
            for item in values
        ]

    return ScriptedBroker(
        submit_steps=_steps("submit"),
        cancel_steps=_steps("cancel_order"),
        close_steps=_steps("close_trade"),
        amend_steps=_steps("amend_protection"),
    )


def _run_position_lifecycle(scenario: DifferentialScenario) -> dict[str, Any]:
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


def _run_live_schedule(scenario: DifferentialScenario) -> dict[str, Any]:
    broker = _scripted_broker_for_scenario(scenario)
    market_data = _ScenarioMarketData(scenario)
    decision_time = datetime.fromisoformat(str(scenario.payload["live"]["now"]))
    clock = FixedClock(decision_time)

    position_service = PositionService(
        broker,
        broker,
        _MemoryNotifier(),
        InMemoryTradeHistoryRepository(),
        clock,
    )
    portfolio = PositionPortfolioService(scenario.pair, position_service, broker, broker)
    analysis = _analysis_service(scenario, market_data)
    app = LiveApplication(
        scenario.pair,
        market_data,
        analysis,
        OrderPlanner(),
        portfolio,
        clock,
    )

    result = app.run_once(
        now=decision_time,
        dry_run=bool(scenario.payload["live"].get("dry_run", True)),
        decision_time=scenario.payload["live"].get("decision_time"),
    )

    if "market_closed" in result.skipped:
        decision = "market_closed"
    elif "update_only" in result.skipped:
        decision = "update_only"
    elif result.analysis is not None and (
        result.plans
        or result.registration.accepted
        or result.registration.rejected
    ):
        decision = "analyze"
    else:
        decision = "idle"

    return {
        "pair": scenario.pair,
        "kind": scenario.kind,
        "scenario_id": scenario.scenario_id,
        "events": [
            {
                "kind": "live_schedule",
                "decision": decision,
                "accepted_count": len(result.registration.accepted),
                "rejected_count": len(result.registration.rejected),
                "plan_count": len(result.plans),
            }
        ],
    }


class _MemoryNotifier:
    def __init__(self) -> None:
        self.messages: list[tuple[str, str, str | None]] = []

    def send(self, message: str, *, category: str = "live", pair: str | None = None) -> None:
        self.messages.append((message, category, pair))


def run_current_scenario_to_path(scenario: DifferentialScenario, output_path: Path) -> None:
    result = run_current_scenario(scenario)
    output_path.write_text(json.dumps(result.trace, ensure_ascii=True), encoding="utf-8")
