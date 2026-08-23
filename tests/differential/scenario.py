from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from .constants import SCENARIO_ROOT, SCENARIO_SCHEMA_VERSION

_ANALYSIS_FRAME_SPECS_PATH = SCENARIO_ROOT.parent.parent / "fixtures" / "analysis_frame_specs.json"
_FRAME_SPEC_KEYS = {
    "latest_time",
    "periods",
    "frequency",
    "base_price",
    "step_pips",
    "body_pips",
    "wick_pips",
}


@dataclass(frozen=True)
class DifferentialScenario:
    scenario_id: str
    kind: str
    pair: str
    payload: dict[str, Any]


class ScenarioValidationError(ValueError):
    pass


_REQUIRED_COMMON_KEYS = {
    "schema_version",
    "scenario_id",
    "kind",
    "pair",
}


_REQUIRED_BY_KIND: dict[str, set[str]] = {
    "analysis_order": {"current_price", "decision_time", "frames"},
    "order_payload": {"current_price", "decision_time", "order_input"},
    "position_lifecycle": {"decision_time", "position"},
    "live_schedule": {"live"},
}


def load_scenario_file(path: Path) -> DifferentialScenario:
    raw = json.loads(path.read_text(encoding="utf-8"))
    validate_scenario(raw, source=str(path))
    raw = _materialize_shared_inputs(raw)
    validate_scenario(raw, source=str(path), materialized=True)
    return DifferentialScenario(
        scenario_id=raw["scenario_id"],
        kind=raw["kind"],
        pair=raw["pair"],
        payload=raw,
    )


def load_all_scenarios() -> list[DifferentialScenario]:
    scenarios = [
        load_scenario_file(path)
        for path in sorted(SCENARIO_ROOT.glob("*.json"))
    ]
    if not scenarios:
        raise ScenarioValidationError(f"No scenarios found under {SCENARIO_ROOT}")
    ids = [scenario.scenario_id for scenario in scenarios]
    duplicates = sorted({scenario_id for scenario_id in ids if ids.count(scenario_id) > 1})
    if duplicates:
        raise ScenarioValidationError(f"Duplicate scenario_id values: {duplicates}")
    return scenarios


def validate_scenario(
    raw: dict[str, Any],
    *,
    source: str = "<memory>",
    materialized: bool = False,
) -> None:
    if not isinstance(raw, dict):
        raise ScenarioValidationError(f"{source}: scenario must be an object")

    missing_common = sorted(_REQUIRED_COMMON_KEYS - set(raw))
    if missing_common:
        raise ScenarioValidationError(f"{source}: missing required keys: {missing_common}")

    if str(raw["schema_version"]) != SCENARIO_SCHEMA_VERSION:
        raise ScenarioValidationError(
            f"{source}: schema_version must be {SCENARIO_SCHEMA_VERSION}, got {raw['schema_version']}"
        )

    kind = raw["kind"]
    if kind not in _REQUIRED_BY_KIND:
        raise ScenarioValidationError(
            f"{source}: kind must be one of {sorted(_REQUIRED_BY_KIND)}, got {kind!r}"
        )

    missing_kind = sorted(_REQUIRED_BY_KIND[kind] - set(raw))
    if missing_kind:
        raise ScenarioValidationError(f"{source}: {kind} missing keys: {missing_kind}")

    scenario_id = raw["scenario_id"]
    if not isinstance(scenario_id, str) or not scenario_id:
        raise ScenarioValidationError(f"{source}: scenario_id must be non-empty string")

    pair = raw["pair"]
    if pair not in {"USD_JPY", "EUR_USD", "AUD_USD"}:
        raise ScenarioValidationError(f"{source}: unsupported pair {pair!r}")

    frames = raw.get("frames")
    if frames is not None and not isinstance(frames, dict):
        raise ScenarioValidationError(f"{source}: frames must be an object when present")

    broker_steps = raw.get("broker_steps")
    if broker_steps is not None:
        if not isinstance(broker_steps, list):
            raise ScenarioValidationError(
                f"{source}: broker_steps must be an ordered list"
            )
        allowed_actions = {
            "submit",
            "order",
            "trade",
            "position",
            "cancel_order",
            "close_trade",
            "amend_protection",
        }
        for index, step in enumerate(broker_steps):
            if not isinstance(step, dict):
                raise ScenarioValidationError(
                    f"{source}: broker_steps[{index}] must be an object"
                )
            if step.get("action") not in allowed_actions:
                raise ScenarioValidationError(
                    f"{source}: broker_steps[{index}] has unsupported action"
                )
            if not isinstance(step.get("response"), dict):
                raise ScenarioValidationError(
                    f"{source}: broker_steps[{index}].response must be an object"
                )
            if step.get("runner", "both") not in {"both", "current", "legacy"}:
                raise ScenarioValidationError(
                    f"{source}: broker_steps[{index}].runner must be both, "
                    "current, or legacy"
                )

    if kind == "analysis_order":
        required_frames = {"M5", "H1", "M30", "S5"}
        frame_keys = set((frames or {}).keys())
        missing_frames = sorted(required_frames - frame_keys)
        if missing_frames:
            raise ScenarioValidationError(f"{source}: analysis_order missing frame keys {missing_frames}")
        for timeframe in sorted(required_frames):
            frame_spec = frames[timeframe]
            if not isinstance(frame_spec, dict):
                raise ScenarioValidationError(
                    f"{source}: frame {timeframe} must be an object"
                )
            if frame_spec.get("source") == "analysis_frame_specs" and not materialized:
                continue
            missing_spec = sorted(_FRAME_SPEC_KEYS - set(frame_spec))
            if missing_spec:
                raise ScenarioValidationError(
                    f"{source}: frame {timeframe} missing keys {missing_spec}"
                )
            if int(frame_spec["periods"]) <= 0:
                raise ScenarioValidationError(
                    f"{source}: frame {timeframe} periods must be positive"
                )
            for sequence_name in ("step_pips", "body_pips"):
                values = frame_spec[sequence_name]
                if not isinstance(values, list) or not values:
                    raise ScenarioValidationError(
                        f"{source}: frame {timeframe} {sequence_name} must be non-empty list"
                    )
    if kind == "live_schedule":
        live = raw["live"]
        if not isinstance(live, dict):
            raise ScenarioValidationError(f"{source}: live must be an object")
        ticks = live.get("ticks")
        if ticks is None and not materialized and live.get("now"):
            return
        if not isinstance(ticks, list) or not ticks:
            raise ScenarioValidationError(
                f"{source}: live.ticks must be a non-empty list"
            )
        for index, tick in enumerate(ticks):
            if not isinstance(tick, dict):
                raise ScenarioValidationError(
                    f"{source}: live.ticks[{index}] must be an object"
                )
            missing_tick = sorted({"now", "price_response"} - set(tick))
            if missing_tick:
                raise ScenarioValidationError(
                    f"{source}: live.ticks[{index}] missing keys {missing_tick}"
                )
            response = tick["price_response"]
            prices = response.get("prices") if isinstance(response, dict) else None
            if not isinstance(prices, list) or len(prices) != 1:
                raise ScenarioValidationError(
                    f"{source}: live.ticks[{index}].price_response must contain "
                    "exactly one price"
                )
            price = prices[0]
            if not isinstance(price, dict):
                raise ScenarioValidationError(
                    f"{source}: live.ticks[{index}].price_response.prices[0] "
                    "must be an object"
                )
            for side in ("bids", "asks"):
                values = price.get(side)
                if (
                    not isinstance(values, list)
                    or len(values) != 1
                    or not isinstance(values[0], dict)
                    or not isinstance(values[0].get("price"), str)
                ):
                    raise ScenarioValidationError(
                        f"{source}: live.ticks[{index}].price_response.prices[0]."
                        f"{side} must contain exactly one string price"
                    )
        startup_orders = live.get("startup_pending_orders", [])
        if not isinstance(startup_orders, list):
            raise ScenarioValidationError(
                f"{source}: live.startup_pending_orders must be a list"
            )
        for index, order in enumerate(startup_orders):
            if not isinstance(order, dict) or not order.get("order_id"):
                raise ScenarioValidationError(
                    f"{source}: live.startup_pending_orders[{index}] requires order_id"
                )
        candidate_count = live.get("candidate_count", 0)
        if not isinstance(candidate_count, int) or candidate_count < 0:
            raise ScenarioValidationError(
                f"{source}: live.candidate_count must be a non-negative integer"
            )
    if kind == "position_lifecycle":
        position = raw["position"]
        if not isinstance(position, dict):
            raise ScenarioValidationError(
                f"{source}: position must be an object"
            )
        initial_slots = position.get("initial_slots")
        if materialized and (
            not isinstance(initial_slots, list) or len(initial_slots) != 15
        ):
            raise ScenarioValidationError(
                f"{source}: position.initial_slots must contain exactly 15 entries"
            )
        if materialized:
            for index, slot in enumerate(initial_slots):
                if slot is not None and not isinstance(slot, dict):
                    raise ScenarioValidationError(
                        f"{source}: position.initial_slots[{index}] must be object or null"
                    )
        case = str(position.get("case", "empty"))
        if case not in {
            "empty",
            "watching",
            "pending_timeout",
            "lc_change",
            "portfolio_acceptance",
            "broker_outcome",
            "linkage_hedge",
            "close_reporting",
            "trade_timeout_disabled",
            "candle_lc",
            "restore",
            "active_dedup",
        }:
            raise ScenarioValidationError(
                f"{source}: unsupported position case {case!r}"
            )
        if case in {"watching", "pending_timeout", "lc_change"}:
            order = position.get("order")
            ticks = position.get("ticks")
            if not isinstance(order, dict):
                raise ScenarioValidationError(
                    f"{source}: {case} position.order must be an object"
                )
            if case == "watching" and order.get("type") not in {"STOP", "LIMIT"}:
                raise ScenarioValidationError(
                    f"{source}: watching order type must be STOP or LIMIT"
                )
            if not isinstance(ticks, list) or not ticks:
                raise ScenarioValidationError(
                    f"{source}: {case} position.ticks must be non-empty list"
                )
            previous_at: datetime | None = None
            for index, tick in enumerate(ticks):
                if not isinstance(tick, dict) or not {"at", "price"} <= set(tick):
                    raise ScenarioValidationError(
                        f"{source}: position.ticks[{index}] requires at and price"
                    )
                at = datetime.fromisoformat(str(tick["at"]))
                if previous_at is not None and at < previous_at:
                    raise ScenarioValidationError(
                        f"{source}: position ticks must be chronological"
                    )
                previous_at = at
            if case == "lc_change" and not order.get("lc_change"):
                raise ScenarioValidationError(
                    f"{source}: lc_change order requires at least one rule"
                )
        if case == "portfolio_acceptance":
            batches = position.get("batches")
            if not isinstance(batches, list) or not batches:
                raise ScenarioValidationError(
                    f"{source}: portfolio_acceptance batches must be non-empty list"
                )
            for batch_index, batch in enumerate(batches):
                if not isinstance(batch, list) or not batch:
                    raise ScenarioValidationError(
                        f"{source}: position.batches[{batch_index}] must be non-empty list"
                    )
                for order_index, order in enumerate(batch):
                    if not isinstance(order, dict):
                        raise ScenarioValidationError(
                            f"{source}: batch {batch_index} order {order_index} must be object"
                        )
                    missing_order = sorted(
                        {
                            "name",
                            "current_price",
                            "target",
                            "direction",
                            "type",
                            "tp",
                            "lc",
                            "units",
                            "priority",
                        }
                        - set(order)
                    )
                    if missing_order:
                        raise ScenarioValidationError(
                            f"{source}: batch {batch_index} order {order_index} missing {missing_order}"
                        )
        if case == "broker_outcome":
            outcome = position.get("outcome")
            if outcome not in {"reject", "exception", "not_found"}:
                raise ScenarioValidationError(
                    f"{source}: broker_outcome outcome must be reject, exception, or not_found"
                )
            if not isinstance(position.get("order"), dict):
                raise ScenarioValidationError(
                    f"{source}: broker_outcome order must be an object"
                )
        if case == "linkage_hedge":
            if not isinstance(position.get("checks"), list) or not position["checks"]:
                raise ScenarioValidationError(
                    f"{source}: linkage_hedge checks must be non-empty list"
                )
        if case == "close_reporting":
            required_close = {
                "name",
                "target_price",
                "close_price",
                "realized_pl",
                "units",
                "order_id",
                "trade_id",
            }
            missing_close = sorted(required_close - set(position))
            if missing_close:
                raise ScenarioValidationError(
                    f"{source}: close_reporting missing keys {missing_close}"
                )
        if case in {"trade_timeout_disabled", "candle_lc"}:
            if not isinstance(position.get("order"), dict):
                raise ScenarioValidationError(
                    f"{source}: {case} order must be an object"
                )
            ticks = position.get("ticks")
            if not isinstance(ticks, list) or not ticks:
                raise ScenarioValidationError(
                    f"{source}: {case} ticks must be non-empty list"
                )
        if case == "candle_lc":
            if not isinstance(position.get("latest_peak"), dict) or not isinstance(
                position.get("previous_candle"), dict
            ):
                raise ScenarioValidationError(
                    f"{source}: candle_lc requires latest_peak and previous_candle"
                )
        if case == "restore":
            if not isinstance(position.get("broker_positions"), list):
                raise ScenarioValidationError(
                    f"{source}: restore broker_positions must be a list"
                )
        if case == "active_dedup":
            if not isinstance(position.get("active"), list) or not isinstance(
                position.get("candidate"), dict
            ):
                raise ScenarioValidationError(
                    f"{source}: active_dedup requires active list and candidate"
                )


def _materialize_shared_inputs(raw: dict[str, Any]) -> dict[str, Any]:
    materialized = deepcopy(raw)
    position = materialized.get("position")
    if isinstance(position, dict):
        slots = position.setdefault("initial_slots", [None] * 15)
        occupied = int(position.get("occupied_slots", 0))
        for index in range(min(occupied, len(slots))):
            if slots[index] is None:
                slots[index] = {
                    "name": f"occupied-{index}",
                    "life": True,
                }
    live = materialized.get("live")
    if isinstance(live, dict) and "ticks" not in live and live.get("now"):
        mid = 150.0 if materialized.get("pair", "USD_JPY").endswith("JPY") else 1.1
        bid = live.get("bid", mid)
        ask = live.get("ask", mid)
        live["ticks"] = [
            {
                "now": live["now"],
                "price_response": {
                    "prices": [
                        {
                            "bids": [{"price": str(bid)}],
                            "asks": [{"price": str(ask)}],
                            "status": "tradeable",
                        }
                    ]
                },
            }
        ]
    frames = materialized.get("frames")
    if not isinstance(frames, dict):
        return materialized

    shared_specs: dict[str, Any] | None = None
    for timeframe, frame_spec in list(frames.items()):
        if not isinstance(frame_spec, dict):
            continue
        if frame_spec.get("source") != "analysis_frame_specs":
            continue
        if shared_specs is None:
            shared_specs = json.loads(
                _ANALYSIS_FRAME_SPECS_PATH.read_text(encoding="utf-8")
            )
        try:
            resolved = deepcopy(shared_specs[str(materialized["pair"])][timeframe])
        except KeyError as error:
            raise ScenarioValidationError(
                f"analysis_frame_specs missing {materialized['pair']}/{timeframe}"
            ) from error
        frames[timeframe] = {
            "source": "analysis_frame_specs",
            **resolved,
            **{
                key: value
                for key, value in frame_spec.items()
                if key != "source"
            },
        }
    return materialized


def select_scenarios(all_scenarios: list[DifferentialScenario], *, scenario_ids: list[str] | None, include_all: bool) -> list[DifferentialScenario]:
    if include_all:
        return list(all_scenarios)
    if not scenario_ids:
        raise ScenarioValidationError("At least one --scenario-id is required unless --all is used")
    by_id = {scenario.scenario_id: scenario for scenario in all_scenarios}
    missing = [scenario_id for scenario_id in scenario_ids if scenario_id not in by_id]
    if missing:
        raise ScenarioValidationError(f"Unknown scenario_ids: {missing}")
    return [by_id[scenario_id] for scenario_id in scenario_ids]
