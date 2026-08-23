from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .constants import SCENARIO_ROOT, SCENARIO_SCHEMA_VERSION


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


def validate_scenario(raw: dict[str, Any], *, source: str = "<memory>") -> None:
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

    if kind == "analysis_order":
        required_frames = {"M5", "H1", "M30", "S5"}
        frame_keys = set((frames or {}).keys())
        missing_frames = sorted(required_frames - frame_keys)
        if missing_frames:
            raise ScenarioValidationError(f"{source}: analysis_order missing frame keys {missing_frames}")


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
