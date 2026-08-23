from __future__ import annotations

import contextlib
import json
import subprocess
import types
from copy import deepcopy
from datetime import date
from pathlib import Path

import pytest

from tests.differential import cli as differential_cli
from tests.differential import orchestrator as differential_orchestrator
from tests.differential import worktree as differential_worktree
from tests.differential.analysis_trace import (
    candidate_summary,
    current_intent_metadata_loss,
    current_semantic_plan,
    object_settings,
)
from tests.differential.compare import (
    AllowlistEntry,
    CompareError,
    compare_traces,
    load_allowlist,
    verify_allowlist_application,
)
from tests.differential.constants import ALLOWLIST_PATH
from tests.differential.constants import BASELINE_COMMIT, BASELINE_TREE
from tests.differential.current_runner import run_current_scenario
from tests.differential.golden import (
    GoldenManifestError,
    build_manifest,
    verify_checked_in_manifest,
)
from tests.differential.legacy_runner import (
    LegacyRunnerError,
    _LegacyFakeOanda,
    _assert_module_paths,
    _NetworkGuard,
)
from tests.differential.normalize import normalize_trace
from tests.differential.offline import OfflineNetworkError
from tests.differential.orchestrator import LegacyProcessError
from tests.differential.scenario import (
    ScenarioValidationError,
    load_all_scenarios,
    load_scenario_file,
)
from tests.differential.scripted_broker import ScriptedBroker
from tests.differential.trace import (
    TraceSerializationError,
    canonical_json_bytes,
    ensure_trace_envelope,
)
from tests.differential.worktree import GitIdentity, baseline_worktree


@pytest.mark.unit
def test_scenarios_are_loadable_and_ids_unique():
    scenarios = load_all_scenarios()
    assert scenarios
    scenario_ids = [scenario.scenario_id for scenario in scenarios]
    assert len(scenario_ids) == len(set(scenario_ids))

    analysis = next(item for item in scenarios if item.kind == "analysis_order")
    assert analysis.payload["frames"]["M5"]["source"] == "analysis_frame_specs"
    assert analysis.payload["frames"]["M5"]["step_pips"]
    positions = [item for item in scenarios if item.kind == "position_lifecycle"]
    assert positions
    assert all(len(item.payload["position"]["initial_slots"]) == 15 for item in positions)


@pytest.mark.unit
def test_checked_in_baseline_contract_identity_matches_constants():
    contract = json.loads(
        Path("tests/differential/baseline_contract.json").read_text(
            encoding="utf-8"
        )
    )

    assert contract["baseline_commit"] == BASELINE_COMMIT
    assert contract["baseline_tree"] == BASELINE_TREE


@pytest.mark.unit
def test_trace_envelope_rejects_identity_override_and_invalid_event():
    with pytest.raises(TraceSerializationError, match="scenario_id mismatch"):
        ensure_trace_envelope(
            {"scenario_id": "wrong", "events": []},
            scenario_id="expected",
            runner="current",
        )
    with pytest.raises(TraceSerializationError, match="kind"):
        ensure_trace_envelope(
            {"events": [{}]},
            scenario_id="expected",
            runner="current",
        )


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
def test_allowlist_application_requires_each_selected_entry_exactly_once():
    entries = [
        AllowlistEntry(
            delta_id="delta-1",
            scenario_id="scenario-a",
            pointer="/events/0/value",
            left=1,
            right=2,
            reason="documented behavior change",
            reference="docs/differential-verification.md",
            expires_on="2099-12-31",
        )
    ]

    verify_allowlist_application(
        allowlist_entries=entries,
        applied_entries=entries,
        scenario_ids={"scenario-a"},
    )
    with pytest.raises(CompareError, match="missing=.*delta-1"):
        verify_allowlist_application(
            allowlist_entries=entries,
            applied_entries=[],
            scenario_ids={"scenario-a"},
        )
    with pytest.raises(CompareError, match="repeated=.*delta-1"):
        verify_allowlist_application(
            allowlist_entries=entries,
            applied_entries=[entries[0], entries[0]],
            scenario_ids={"scenario-a"},
        )
    orphan = [
        AllowlistEntry(
            delta_id="orphan",
            scenario_id="removed-scenario",
            pointer="/events/0/value",
            left=1,
            right=2,
            reason="orphan",
            reference="docs/differential-verification.md",
            expires_on="2099-12-31",
        )
    ]
    with pytest.raises(CompareError, match="orphan=.*orphan"):
        verify_allowlist_application(
            allowlist_entries=[*entries, *orphan],
            applied_entries=entries,
            scenario_ids={"scenario-a"},
            known_scenario_ids={"scenario-a", "scenario-b"},
        )


@pytest.mark.unit
def test_allowlist_rejects_unknown_entry_keys(tmp_path):
    path = tmp_path / "allowlist.json"
    path.write_text(
        json.dumps(
            [
                {
                    "delta_id": "delta-1",
                    "scenario_id": "scenario-a",
                    "pointer": "/events/0/value",
                    "left": 1,
                    "right": 2,
                    "reason": "documented",
                    "reference": "docs/differential-verification.md",
                    "expires_on": "2099-12-31",
                    "unexpected": True,
                }
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(CompareError, match="unknown keys"):
        load_allowlist(path)


@pytest.mark.unit
def test_allowlisted_first_difference_does_not_hide_later_unexpected_difference():
    baseline = {"events": [{"allowed": 1, "unexpected": "legacy"}]}
    current = {"events": [{"allowed": 2, "unexpected": "current"}]}
    allow = [
        AllowlistEntry(
            delta_id="delta-1",
            scenario_id="scenario-a",
            pointer="/events/0/allowed",
            left=1,
            right=2,
            reason="documented behavior change",
            reference="docs/differential-verification.md#intentional-deltas",
            expires_on="2099-12-31",
        )
    ]

    result = compare_traces(
        scenario_id="scenario-a",
        baseline_trace=baseline,
        current_trace=current,
        allowlist_entries=allow,
    )

    assert result.matched is False
    assert result.mismatch is not None
    assert result.mismatch.pointer == "/events/0/unexpected"
    assert result.allowlist_applied_entries == tuple(allow)


@pytest.mark.unit
def test_allowlisted_added_key_does_not_hide_wrong_added_value():
    allow = [
        AllowlistEntry(
            delta_id="added-key",
            scenario_id="scenario-a",
            pointer="/events/0/payload/timeInForce",
            left={"$missing": True},
            right="GTC",
            reason="wire contract",
            reference="docs/differential-verification.md",
            expires_on="2099-12-31",
        )
    ]

    allowed = compare_traces(
        scenario_id="scenario-a",
        baseline_trace={"events": [{"payload": {}}]},
        current_trace={"events": [{"payload": {"timeInForce": "GTC"}}]},
        allowlist_entries=allow,
    )
    wrong = compare_traces(
        scenario_id="scenario-a",
        baseline_trace={"events": [{"payload": {}}]},
        current_trace={"events": [{"payload": {"timeInForce": "WRONG"}}]},
        allowlist_entries=allow,
    )

    assert allowed.matched is True
    assert wrong.matched is False
    assert wrong.mismatch is not None
    assert wrong.mismatch.pointer == "/events/0/payload/timeInForce"


@pytest.mark.unit
def test_allowlist_rejects_container_values(tmp_path):
    path = tmp_path / "allowlist.json"
    path.write_text(
        json.dumps(
            [
                {
                    "delta_id": "container",
                    "scenario_id": "scenario-a",
                    "pointer": "/events/0/payload",
                    "left": ["price"],
                    "right": ["price", "timeInForce"],
                    "reason": "too broad",
                    "reference": "docs/differential-verification.md",
                    "expires_on": "2099-12-31",
                }
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="container"):
        load_allowlist(path)


@pytest.mark.unit
def test_allowlist_sha256_matcher_keeps_large_values_exact():
    import hashlib

    value = "large legacy notification\n" * 100
    digest = hashlib.sha256(canonical_json_bytes(value)).hexdigest()
    result = compare_traces(
        scenario_id="scenario-a",
        baseline_trace={"events": [{"message": value}]},
        current_trace={"events": [{"message": "current summary"}]},
        allowlist_entries=[
            AllowlistEntry(
                delta_id="message-format",
                scenario_id="scenario-a",
                pointer="/events/0/message",
                left={"$sha256": digest},
                right="current summary",
                reason="documented format change",
                reference="docs/differential-verification.md",
                expires_on="2099-12-31",
            )
        ],
    )

    assert result.matched is True


@pytest.mark.unit
def test_allowlist_sha256_subtree_matcher_covers_only_exact_descendants():
    import hashlib

    baseline_sequence = ["quote", "analysis", "sync"]
    current_sequence = ["quote", "analysis", "register", "sync"]
    allow = [
        AllowlistEntry(
            delta_id="sequence-format",
            scenario_id="scenario-a",
            pointer="/events/0/sequence",
            left={
                "$sha256": hashlib.sha256(
                    canonical_json_bytes(baseline_sequence)
                ).hexdigest()
            },
            right={
                "$sha256": hashlib.sha256(
                    canonical_json_bytes(current_sequence)
                ).hexdigest()
            },
            reason="documented orchestration delta",
            reference="docs/differential-verification.md",
            expires_on="2099-12-31",
        )
    ]
    allowed = compare_traces(
        scenario_id="scenario-a",
        baseline_trace={"events": [{"sequence": baseline_sequence}]},
        current_trace={"events": [{"sequence": current_sequence}]},
        allowlist_entries=allow,
    )
    wrong = compare_traces(
        scenario_id="scenario-a",
        baseline_trace={"events": [{"sequence": baseline_sequence}]},
        current_trace={
            "events": [{"sequence": ["quote", "analysis", "WRONG", "sync"]}]
        },
        allowlist_entries=allow,
    )

    assert allowed.matched is True
    assert wrong.matched is False


@pytest.mark.unit
def test_normalize_only_rewrites_semantic_broker_ids_and_price_fields():
    trace = {
        "pair": "USD_JPY",
        "scenario_id": "order-payload-123",
        "events": [
            {
                "order_id": "123",
                "units": "8000",
                "price": 150.12349,
                "distance_pips": 3.14159,
                "median": 3.14159,
                "median_p": 3.14159,
                "range_min": 3.14159,
                "range_max": 9.87654,
                "tp_range": 0.12349,
                "lc_range": 0.12341,
                "take_profit_range": 0.12348,
                "stop_loss_range": 0.12342,
                "spread": 0.00149,
            }
        ],
    }

    normalized = normalize_trace(trace)

    assert normalized["scenario_id"] == "order-payload-123"
    assert normalized["events"][0]["order_id"] == "broker-id-001"
    assert normalized["events"][0]["units"] == "8000"
    assert normalized["events"][0]["price"] == 150.123
    assert normalized["events"][0]["distance_pips"] == 3.14159
    assert normalized["events"][0]["median"] == 3.14159
    assert normalized["events"][0]["median_p"] == 3.14159
    assert normalized["events"][0]["range_min"] == 3.14159
    assert normalized["events"][0]["range_max"] == 9.87654
    assert normalized["events"][0]["tp_range"] == 0.12349
    assert normalized["events"][0]["lc_range"] == 0.12341
    assert normalized["events"][0]["take_profit_range"] == 0.12348
    assert normalized["events"][0]["stop_loss_range"] == 0.12342
    assert normalized["events"][0]["spread"] == 0.00149


@pytest.mark.unit
def test_analysis_projection_preserves_new_candidate_and_strategy_fields():
    class _Profile:
        inherited_profile_setting = {3, 1, 2}

    class _Strategy:
        inherited_strategy_setting = "visible"

        def __init__(self):
            self.profile = _Profile()
            self.pair = "EUR_USD"
            self.new_strategy_setting = 3.14159

    strategy = _Strategy()

    summary = candidate_summary(
        [
            {
                "strategy": strategy,
                "effective_tp_pips": 5.0,
                "order_permission": False,
                "new_candidate_field": "visible",
            }
        ]
    )[0]

    assert summary["effective_tp_pips"] == 5.0
    assert summary["order_permission"] is False
    assert summary["new_candidate_field"] == "visible"
    assert summary["strategy"]["settings"]["new_strategy_setting"] == 3.14159
    assert summary["strategy"]["settings"]["inherited_strategy_setting"] == "visible"
    assert object_settings(strategy.profile)["inherited_profile_setting"] == [1, 2, 3]


@pytest.mark.unit
def test_current_semantic_projection_preserves_metadata_and_reports_adapter_loss():
    intent = types.SimpleNamespace(
        metadata={
            "legacy_plan_metadata": {"line_side": "lower"},
            "units": 999,
            "effective_tp_pips": 5.0,
            "order_permission": False,
            "new_strategy_field": "visible",
        }
    )
    adapter_plan = {"units": 166, "order_permission": False}

    semantic_plan = current_semantic_plan(intent, adapter_plan)
    metadata_loss = current_intent_metadata_loss(intent, adapter_plan)

    assert semantic_plan["units"] == 166
    assert semantic_plan["effective_tp_pips"] == 5.0
    assert semantic_plan["new_strategy_field"] == "visible"
    assert metadata_loss == {
        "effective_tp_pips": 5.0,
        "new_strategy_field": "visible",
    }


@pytest.mark.unit
def test_current_analysis_trace_exposes_enriched_candidate_and_metadata_loss():
    scenario = next(
        item
        for item in load_all_scenarios()
        if item.scenario_id == "analysis-order-eur-usd"
    )

    event = run_current_scenario(scenario).trace["events"][0]
    enriched = event["candidates"]["enriched"]["future_break"][0]

    assert enriched["candidate"]["effective_tp_pips"] == 5.0
    assert enriched["candidate"]["order_permission"] is True
    assert enriched["plan"]["path_tp_adjusted"] is True
    assert event["intent_metadata_loss"][0]["path_tp_adjusted"] is True
    profile = event["strategy_profiles"]["LineStrategyProfileEurUsd"]
    assert profile["m5_lc_pips"] == 7.5
    assert profile["top10_conditions"][7]["label"] == (
        "EUR Top8 lower 8-10p lineStr5-8"
    )


@pytest.mark.unit
def test_real_analysis_multi_selection_preserves_candidate_plan_and_reason_order():
    scenario = next(
        item
        for item in load_all_scenarios()
        if item.scenario_id == "analysis-order-multi-eur-usd"
    )

    event = run_current_scenario(scenario).trace["events"][0]
    selected = event["candidates"]["selected"]["future_break"]

    assert len(selected) == 9
    assert len(event["plans"]) == 9
    assert [candidate["line_price"] for candidate in selected] == [
        1.1092,
        1.1086,
        1.10835,
        1.1077,
        1.1068,
        1.1059,
        1.10565,
        1.105,
        1.10475,
    ]
    assert selected[0]["recommended_reasons"] == [
        "EUR Top5 session21-23 latestPeakRSI60-67.5",
        "EUR Top8 lower 8-10p lineStr5-8",
    ]
    assert selected[1]["recommended_reasons"] == [
        "EUR Top5 session21-23 latestPeakRSI60-67.5"
    ]
    assert [plan["name"] for plan in event["plans"]] == [
        "M5LineBreakout_lower_0_22:00",
        "M5LineBreakout_lower_1_22:00",
        "M5LineBreakout_lower_2_22:00",
        "M5LineBreakout_lower_3_22:00",
        "M5LineBreakout_lower_5_22:00",
        "M5LineBreakout_lower_7_22:00",
        "M5LineBreakout_lower_8_22:00",
        "M5LineBreakout_lower_9_22:00",
        "M5LineBreakout_lower_10_22:00",
    ]


@pytest.mark.unit
def test_allowlist_rejects_expired_entries(tmp_path):
    path = tmp_path / "allowlist.json"
    path.write_text(
        json.dumps(
            [
                {
                    "delta_id": "expired",
                    "scenario_id": "scenario-a",
                    "pointer": "/events/0/value",
                    "left": 1,
                    "right": 2,
                    "reason": "temporary",
                    "reference": "docs/differential-verification.md",
                    "expires_on": "2000-01-01",
                }
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="expired"):
        load_allowlist(path, as_of=date(2000, 1, 2))


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
def test_legacy_module_path_check_rejects_current_workspace_contamination(
    monkeypatch,
    tmp_path,
):
    expected = tmp_path / "baseline"
    contaminated = types.ModuleType("contaminated")
    contaminated.__file__ = str(Path("tests/differential/current_runner.py").resolve())
    monkeypatch.setenv("LEGACY_EXPECTED_WORKTREE", str(expected))

    with pytest.raises(LegacyRunnerError, match="outside"):
        _assert_module_paths({"contaminated": contaminated})


@pytest.mark.unit
def test_legacy_network_guard_blocks_requests_and_records_attempt():
    import requests

    guard = _NetworkGuard()
    guard.install()
    try:
        with pytest.raises(AssertionError, match="Network access is prohibited"):
            requests.get("https://example.invalid")
    finally:
        guard.uninstall()

    assert guard.calls == ["requests:get:https://example.invalid"]


@pytest.mark.unit
def test_current_runner_can_execute_each_scenario_shape_without_import_errors():
    scenarios = load_all_scenarios()
    for scenario in scenarios:
        trace = run_current_scenario(scenario).trace
        envelope = ensure_trace_envelope(trace, scenario_id=scenario.scenario_id, runner="current")
        assert envelope["scenario_id"] == scenario.scenario_id
        assert isinstance(envelope["events"], list)


@pytest.mark.unit
def test_live_spread_boundary_trace_uses_pair_precision():
    scenario = next(
        item
        for item in load_all_scenarios()
        if item.scenario_id == "live-spread-boundary-usd-jpy"
    )

    events = run_current_scenario(scenario).trace["events"]

    assert events[0]["quote_count"] == 1
    assert events[0]["quote"] == {
        "bid": 150.0,
        "ask": 150.012,
        "mid": 150.006,
        "spread": 0.012,
        "tradeable": True,
    }
    assert events[1]["quote_count"] == 1
    assert events[1]["quote"]["spread"] == 0.011


@pytest.mark.unit
@pytest.mark.parametrize("adapter_name", ["current", "legacy"])
def test_raw_broker_steps_reject_mismatch_underflow_and_leftovers(adapter_name):
    def adapter(steps):
        if adapter_name == "current":
            return ScriptedBroker(raw_steps=steps)
        broker = _LegacyFakeOanda("test", "test", "practice")
        broker.set_broker_steps(steps)
        return broker

    wrong = adapter(
        [{"action": "submit", "response": {"state": "PENDING", "order_id": "1"}}]
    )
    with pytest.raises(ValueError, match="action mismatch"):
        if adapter_name == "current":
            wrong.order("1")
        else:
            wrong.OrderDetails_exe("1")

    empty = adapter([])
    with pytest.raises(ValueError, match="underflow"):
        if adapter_name == "current":
            empty.order("1")
        else:
            empty.OrderDetails_exe("1")

    leftover = adapter(
        [{"action": "order", "response": {"found": False}}]
    )
    with pytest.raises(ValueError, match="unconsumed"):
        leftover.assert_broker_steps_consumed()


@pytest.mark.unit
def test_golden_capture_failure_leaves_previous_directory_byte_identical(
    monkeypatch,
    tmp_path,
):
    golden = tmp_path / "golden"
    golden.mkdir()
    (golden / "manifest.json").write_bytes(b"old-manifest\n")
    (golden / "old.trace.json").write_bytes(b"old-trace\n")
    before = {
        path.relative_to(golden): path.read_bytes()
        for path in golden.rglob("*")
        if path.is_file()
    }
    scenarios = load_all_scenarios()[:2]
    captures = 0

    def fail_second_capture(*, repo_root, scenario):
        del repo_root
        nonlocal captures
        captures += 1
        if captures == 2:
            raise RuntimeError("capture failed")
        trace = ensure_trace_envelope(
            {"events": [{"kind": "probe"}]},
            scenario_id=scenario.scenario_id,
            runner="legacy",
        )
        return types.SimpleNamespace(trace=trace, trace_sha256="probe")

    monkeypatch.setattr(differential_cli, "GOLDEN_ROOT", golden)
    monkeypatch.setattr(
        differential_cli,
        "verify_baseline_reference",
        lambda _repo_root: None,
    )
    monkeypatch.setattr(
        differential_cli,
        "capture_legacy_trace",
        fail_second_capture,
    )

    with pytest.raises(RuntimeError, match="capture failed"):
        differential_cli._update_golden(Path.cwd(), scenarios)

    after = {
        path.relative_to(golden): path.read_bytes()
        for path in golden.rglob("*")
        if path.is_file()
    }
    assert after == before
    assert not golden.with_name(golden.name + ".replacement").exists()
    assert not golden.with_name(golden.name + ".backup").exists()


@pytest.mark.unit
def test_golden_replacement_failure_restores_previous_directory(
    monkeypatch,
    tmp_path,
):
    golden = tmp_path / "golden"
    golden.mkdir()
    (golden / "manifest.json").write_bytes(b"old-manifest\n")
    (golden / "old.trace.json").write_bytes(b"old-trace\n")
    before = {
        path.relative_to(golden): path.read_bytes()
        for path in golden.rglob("*")
        if path.is_file()
    }
    scenarios = load_all_scenarios()[:2]

    def capture(*, repo_root, scenario):
        del repo_root
        trace = ensure_trace_envelope(
            {"events": [{"kind": "probe"}]},
            scenario_id=scenario.scenario_id,
            runner="legacy",
        )
        return types.SimpleNamespace(trace=trace, trace_sha256="probe")

    replacement = golden.with_name(golden.name + ".replacement")
    original_replace = Path.replace

    def fail_replacement(path, target):
        if path == replacement and Path(target) == golden:
            raise OSError("replacement rename failed")
        return original_replace(path, target)

    monkeypatch.setattr(differential_cli, "GOLDEN_ROOT", golden)
    monkeypatch.setattr(
        differential_cli,
        "verify_baseline_reference",
        lambda _repo_root: None,
    )
    monkeypatch.setattr(differential_cli, "capture_legacy_trace", capture)
    monkeypatch.setattr(Path, "replace", fail_replacement)

    with pytest.raises(OSError, match="replacement rename failed"):
        differential_cli._update_golden(Path.cwd(), scenarios)

    after = {
        path.relative_to(golden): path.read_bytes()
        for path in golden.rglob("*")
        if path.is_file()
    }
    assert after == before
    assert not replacement.exists()
    assert not golden.with_name(golden.name + ".backup").exists()


@pytest.mark.unit
@pytest.mark.parametrize(
    ("completed_or_error", "expected_returncode", "expected_signal", "timed_out"),
    [
        (
            subprocess.TimeoutExpired(
                cmd=["legacy"],
                timeout=120,
                output="partial stdout",
                stderr="partial stderr",
            ),
            -1,
            None,
            True,
        ),
        (
            subprocess.CompletedProcess(
                args=["legacy"],
                returncode=-15,
                stdout="signal stdout",
                stderr="signal stderr",
            ),
            -15,
            15,
            False,
        ),
    ],
)
def test_legacy_process_error_preserves_timeout_and_signal_outcome(
    monkeypatch,
    tmp_path,
    completed_or_error,
    expected_returncode,
    expected_signal,
    timed_out,
):
    worktree_path = tmp_path / "baseline"
    worktree_path.mkdir()

    @contextlib.contextmanager
    def fake_worktree(_repo_root, *, commit):
        del commit
        yield types.SimpleNamespace(worktree_path=worktree_path)

    def fake_run(*_args, **_kwargs):
        if isinstance(completed_or_error, BaseException):
            raise completed_or_error
        return completed_or_error

    monkeypatch.setattr(
        differential_orchestrator,
        "baseline_worktree",
        fake_worktree,
    )
    monkeypatch.setattr(differential_orchestrator.subprocess, "run", fake_run)
    scenario = load_all_scenarios()[0]

    with pytest.raises(LegacyProcessError) as captured:
        differential_orchestrator._run_legacy_in_isolated_worktree(
            repo_root=Path.cwd(),
            scenario=scenario,
        )

    outcome = captured.value.outcome
    assert outcome.returncode == expected_returncode
    assert outcome.signal == expected_signal
    assert outcome.timed_out is timed_out
    assert "stdout" in outcome.stdout
    assert "stderr" in outcome.stderr


@pytest.mark.unit
def test_exceptional_baseline_worktree_exit_verifies_and_removes_registration(
    monkeypatch,
    tmp_path,
):
    calls = []

    def fake_git(repo_root, *args):
        calls.append((Path(repo_root), args))
        if args[:2] == ("rev-parse", "HEAD"):
            return "baseline-commit"
        if args[:2] == ("status", "--porcelain"):
            return ""
        return ""

    monkeypatch.setattr(
        differential_worktree,
        "verify_baseline_reference",
        lambda _repo_root, *, commit: GitIdentity(commit, "tree"),
    )
    monkeypatch.setattr(differential_worktree, "_git", fake_git)

    with pytest.raises(RuntimeError, match="body failed"):
        with baseline_worktree(tmp_path, commit="baseline-commit"):
            raise RuntimeError("body failed")

    actions = [args for _root, args in calls]
    remove_index = next(
        index
        for index, args in enumerate(actions)
        if args[:3] == ("worktree", "remove", "--force")
    )
    assert ("rev-parse", "HEAD") in actions[:remove_index]
    assert ("status", "--porcelain") in actions[:remove_index]
    assert actions[remove_index][:3] == ("worktree", "remove", "--force")


@pytest.mark.unit
def test_current_runner_is_repeatable_across_two_in_process_passes():
    scenarios = load_all_scenarios()
    first = {
        scenario.scenario_id: canonical_json_bytes(
            normalize_trace(run_current_scenario(scenario).trace)
        )
        for scenario in scenarios
    }
    second = {
        scenario.scenario_id: canonical_json_bytes(
            normalize_trace(run_current_scenario(scenario).trace)
        )
        for scenario in scenarios
    }

    assert second == first


@pytest.mark.unit
def test_current_runner_blocks_network_leak(monkeypatch):
    import requests

    scenario = next(
        item for item in load_all_scenarios() if item.kind == "order_payload"
    )

    def _leaking_runner(_scenario):
        requests.get("https://example.invalid")

    monkeypatch.setattr(
        "tests.differential.current_runner._run_order_payload",
        _leaking_runner,
    )

    with pytest.raises(OfflineNetworkError, match="Network access is prohibited"):
        run_current_scenario(scenario)


@pytest.mark.unit
def test_default_allowlist_file_exists_and_is_json_list():
    assert ALLOWLIST_PATH.exists()
    raw = json.loads(ALLOWLIST_PATH.read_text(encoding="utf-8"))
    assert isinstance(raw, list)


@pytest.mark.unit
def test_manifest_verification_detects_runner_scenario_and_trace_tampering(
    tmp_path,
):
    scenarios = load_all_scenarios()
    traces = {
        scenario.scenario_id: ensure_trace_envelope(
            {"events": [{"kind": "probe"}]},
            scenario_id=scenario.scenario_id,
            runner="trace-runner",
        )
        for scenario in scenarios
    }
    trace_root = tmp_path / "golden"
    trace_root.mkdir()
    for scenario_id, trace in traces.items():
        path = trace_root / f"{scenario_id}.trace.json"
        path.write_bytes(canonical_json_bytes(trace))
    runner = Path("tests/differential/trace.py").resolve()
    manifest = build_manifest(
        scenarios=scenarios,
        traces=traces,
        runner_files=[runner],
    )

    runner_tampered = deepcopy(manifest)
    runner_tampered["runner_sha256"] = {
        str(runner.relative_to(Path.cwd())): "bad"
    }
    with pytest.raises(GoldenManifestError, match="runner_sha256"):
        verify_checked_in_manifest(
            scenarios=scenarios,
            runner_files=[runner],
            manifest=runner_tampered,
            trace_root=trace_root,
        )

    scenario_id = scenarios[0].scenario_id
    scenario_tampered = deepcopy(manifest)
    scenario_tampered["scenarios"][scenario_id]["scenario_sha256"] = "bad"
    with pytest.raises(GoldenManifestError, match="scenario_sha256"):
        verify_checked_in_manifest(
            scenarios=scenarios,
            runner_files=[runner],
            manifest=scenario_tampered,
            trace_root=trace_root,
        )

    trace_tampered = deepcopy(manifest)
    trace_tampered["scenarios"][scenario_id]["trace_sha256"] = "bad"
    with pytest.raises(GoldenManifestError, match="trace_sha256"):
        verify_checked_in_manifest(
            scenarios=scenarios,
            runner_files=[runner],
            manifest=trace_tampered,
            trace_root=trace_root,
        )

    path_tampered = deepcopy(manifest)
    path_tampered["scenarios"][scenario_id]["trace_file"] = (
        "../external.trace.json"
    )
    with pytest.raises(GoldenManifestError, match="trace_file"):
        verify_checked_in_manifest(
            scenarios=scenarios,
            runner_files=[runner],
            manifest=path_tampered,
            trace_root=trace_root,
        )

    envelope_tampered = deepcopy(traces[scenario_id])
    envelope_tampered["scenario_id"] = "wrong"
    trace_path = trace_root / f"{scenario_id}.trace.json"
    trace_path.write_bytes(canonical_json_bytes(envelope_tampered))
    envelope_manifest = deepcopy(manifest)
    envelope_manifest["scenarios"][scenario_id]["trace_sha256"] = __import__(
        "hashlib"
    ).sha256(trace_path.read_bytes()).hexdigest()
    with pytest.raises(GoldenManifestError, match="envelope"):
        verify_checked_in_manifest(
            scenarios=scenarios,
            runner_files=[runner],
            manifest=envelope_manifest,
            trace_root=trace_root,
        )
    trace_path.write_bytes(canonical_json_bytes(traces[scenario_id]))

    noncanonical_manifest = deepcopy(manifest)
    trace_path.write_text(
        json.dumps(traces[scenario_id], indent=2),
        encoding="utf-8",
    )
    noncanonical_manifest["scenarios"][scenario_id]["trace_sha256"] = (
        __import__("hashlib").sha256(trace_path.read_bytes()).hexdigest()
    )
    with pytest.raises(GoldenManifestError, match="canonical"):
        verify_checked_in_manifest(
            scenarios=scenarios,
            runner_files=[runner],
            manifest=noncanonical_manifest,
            trace_root=trace_root,
        )

    version_tampered = deepcopy(manifest)
    version_tampered["python_version"] = "0.0.0"
    with pytest.raises(GoldenManifestError, match="python_version"):
        verify_checked_in_manifest(
            scenarios=scenarios,
            runner_files=[runner],
            manifest=version_tampered,
            trace_root=trace_root,
        )

    package_tampered = deepcopy(manifest)
    package_tampered["package_versions"]["pandas"] = "wrong"
    with pytest.raises(GoldenManifestError, match="package_versions"):
        verify_checked_in_manifest(
            scenarios=scenarios,
            runner_files=[runner],
            manifest=package_tampered,
            trace_root=trace_root,
        )

    unknown_key = deepcopy(manifest)
    unknown_key["unexpected"] = True
    with pytest.raises(GoldenManifestError, match="keys mismatch"):
        verify_checked_in_manifest(
            scenarios=scenarios,
            runner_files=[runner],
            manifest=unknown_key,
            trace_root=trace_root,
        )
