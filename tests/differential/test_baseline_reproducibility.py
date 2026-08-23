from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from tests.differential.compare import compare_traces
from tests.differential.bootstrap import verify_baseline_contract
from tests.differential.constants import BASELINE_COMMIT, BASELINE_TREE
from tests.differential.golden import load_golden_trace
from tests.differential.orchestrator import capture_legacy_trace, verify_trace_reproducibility
from tests.differential.scenario import load_all_scenarios
from tests.differential.worktree import verify_baseline_reference


@pytest.mark.baseline_replay
@pytest.mark.slow
def test_baseline_commit_and_tree_are_exact():
    repo_root = Path(__file__).resolve().parents[2]
    identity = verify_baseline_reference(repo_root)

    assert identity.commit == BASELINE_COMMIT
    assert identity.tree == BASELINE_TREE
    contract = verify_baseline_contract(repo_root)
    assert contract["baseline_commit"] == BASELINE_COMMIT
    assert contract["baseline_tree"] == BASELINE_TREE
    assert contract["symbols"]


@pytest.mark.unit
def test_bootstrap_oracle_provenance_is_explicit_and_hashes_are_stable():
    repo_root = Path(__file__).resolve().parents[2]
    contract = json.loads(
        (repo_root / "tests/differential/baseline_contract.json").read_text(
            encoding="utf-8"
        )
    )
    provenance = contract["bootstrap_oracles"]

    assert "must not be inferred" in provenance["relationship"]
    assert "supersede" in provenance["disposition"]
    for filename, expected in provenance["sha256"].items():
        content = (repo_root / "tests/fixtures" / filename).read_bytes()
        assert hashlib.sha256(content).hexdigest() == expected


@pytest.mark.baseline_replay
@pytest.mark.slow
def test_legacy_multi_selection_scenario_keeps_final_plan_order():
    repo_root = Path(__file__).resolve().parents[2]
    scenario = next(
        item
        for item in load_all_scenarios()
        if item.scenario_id == "analysis-order-multi-eur-usd"
    )

    event = capture_legacy_trace(
        repo_root=repo_root,
        scenario=scenario,
    ).trace["events"][0]

    assert len(event["candidates"]["selected"]["future_break"]) == 9
    assert [plan["name"] for plan in event["plans"]] == [
        "M5LineBreakout_lower_0_22:00",
        "M5LineBreakout_lower_1_22:00",
        "M5LineBreakout_lower_3_22:00",
        "M5LineBreakout_lower_5_22:00",
        "M5LineBreakout_lower_7_22:00",
        "M5LineBreakout_lower_9_22:00",
    ]


@pytest.mark.baseline_replay
@pytest.mark.slow
def test_legacy_capture_is_deterministic_for_all_scenarios():
    repo_root = Path(__file__).resolve().parents[2]
    failures = []
    for scenario in load_all_scenarios():
        matched, first_sha, second_sha = verify_trace_reproducibility(
            repo_root=repo_root,
            scenario=scenario,
        )
        if not matched or first_sha != second_sha:
            failures.append((scenario.scenario_id, first_sha, second_sha))

    assert not failures, failures


@pytest.mark.baseline_replay
@pytest.mark.slow
def test_legacy_replay_matches_checked_in_golden_for_all_scenarios():
    repo_root = Path(__file__).resolve().parents[2]
    scenarios = load_all_scenarios()

    failures: list[str] = []
    for scenario in scenarios:
        captured = capture_legacy_trace(repo_root=repo_root, scenario=scenario)
        golden = load_golden_trace(scenario.scenario_id)
        result = compare_traces(
            scenario_id=scenario.scenario_id,
            baseline_trace=golden,
            current_trace=captured.trace,
            allowlist_entries=[],
        )
        if not result.matched:
            pointer = result.mismatch.pointer if result.mismatch else "stale_allowlist"
            failures.append(f"{scenario.scenario_id}: {pointer}")

    assert not failures, "\n".join(failures)
