from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.differential.compare import (
    AllowlistEntry,
    compare_traces,
    load_allowlist,
)
from tests.differential.constants import ALLOWLIST_PATH
from tests.differential.current_runner import run_current_scenario
from tests.differential.normalize import normalize_trace
from tests.differential.scenario import (
    ScenarioValidationError,
    load_all_scenarios,
    load_scenario_file,
)
from tests.differential.trace import canonical_json_bytes, ensure_trace_envelope


@pytest.mark.unit
def test_scenarios_are_loadable_and_ids_unique():
    scenarios = load_all_scenarios()
    assert scenarios
    scenario_ids = [scenario.scenario_id for scenario in scenarios]
    assert len(scenario_ids) == len(set(scenario_ids))


@pytest.mark.unit
def test_scenario_schema_rejects_unknown_pair(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": "1.0.0",
                "scenario_id": "bad",
                "kind": "analysis_order",
                "pair": "GBP_USD",
                "current_price": 1.2,
                "decision_time": "2026/01/02 11:55:00",
                "frames": {"M5": {}, "H1": {}, "M30": {}, "S5": {}},
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ScenarioValidationError):
        load_scenario_file(path)


@pytest.mark.unit
def test_normalize_absorbs_mapping_order_but_preserves_list_order():
    left = {"pair": "USD_JPY", "events": [{"values": [1, 2, 3], "k": {"b": 2, "a": 1}}]}
    right_same_mapping_different_order = {
        "events": [{"k": {"a": 1, "b": 2}, "values": [1, 2, 3]}],
        "pair": "USD_JPY",
    }

    assert canonical_json_bytes(normalize_trace(left)) == canonical_json_bytes(normalize_trace(right_same_mapping_different_order))

    right_list_reordered = {"pair": "USD_JPY", "events": [{"values": [1, 3, 2], "k": {"a": 1, "b": 2}}]}
    result = compare_traces(
        scenario_id="x",
        baseline_trace=left,
        current_trace=right_list_reordered,
        allowlist_entries=[],
    )
    assert result.matched is False
    assert result.mismatch is not None
    assert result.mismatch.pointer.endswith("/events/0/values/1")


@pytest.mark.unit
def test_compare_allowlist_expected_unexpected_and_stale_cases():
    baseline = {"pair": "USD_JPY", "events": [{"value": 1.001}]}
    current = {"pair": "USD_JPY", "events": [{"value": 1.002}]}

    mismatch = compare_traces(
        scenario_id="scenario-a",
        baseline_trace=baseline,
        current_trace=current,
        allowlist_entries=[],
    )
    assert mismatch.matched is False
    assert mismatch.allowlist_applied is None

    allow = [
        AllowlistEntry(
            delta_id="delta-1",
            scenario_id="scenario-a",
            pointer="/events/0/value",
            left=1.001,
            right=1.002,
            reason="known rounding",
            reference="docs/test",
            expires_on="2099-12-31",
        )
    ]
    allowed = compare_traces(
        scenario_id="scenario-a",
        baseline_trace=baseline,
        current_trace=current,
        allowlist_entries=allow,
    )
    assert allowed.matched is True
    assert allowed.allowlist_applied is not None

    stale = compare_traces(
        scenario_id="scenario-a",
        baseline_trace=baseline,
        current_trace=baseline,
        allowlist_entries=allow,
    )
    assert stale.matched is False
    assert stale.mismatch is None
    assert stale.stale_entries


@pytest.mark.unit
def test_allowlist_rejects_wildcard_pointer(tmp_path):
    path = tmp_path / "allowlist.json"
    path.write_text(
        json.dumps(
            [
                {
                    "delta_id": "x",
                    "scenario_id": "s",
                    "pointer": "/events/*/value",
                    "left": 1,
                    "right": 2,
                    "reason": "x",
                    "reference": "x",
                    "expires_on": "2099-01-01",
                }
            ]
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError):
        load_allowlist(path)


@pytest.mark.unit
def test_current_runner_source_does_not_import_root_legacy_modules():
    source = Path("tests/differential/current_runner.py").read_text(encoding="utf-8")
    forbidden = (
        "import classOrderCreate",
        "import classPosition",
        "import classPositionControl",
        "import classOanda",
        "import fLineAnalysis",
        "import fAnalysis_order_Main",
        "import main_exe",
    )
    assert all(token not in source for token in forbidden)


@pytest.mark.unit
def test_current_runner_can_execute_each_scenario_shape_without_import_errors():
    scenarios = load_all_scenarios()
    for scenario in scenarios:
        trace = run_current_scenario(scenario).trace
        envelope = ensure_trace_envelope(trace, scenario_id=scenario.scenario_id, runner="current")
        assert envelope["scenario_id"] == scenario.scenario_id
        assert isinstance(envelope["events"], list)


@pytest.mark.unit
def test_default_allowlist_file_exists_and_is_json_list():
    assert ALLOWLIST_PATH.exists()
    raw = json.loads(ALLOWLIST_PATH.read_text(encoding="utf-8"))
    assert isinstance(raw, list)
