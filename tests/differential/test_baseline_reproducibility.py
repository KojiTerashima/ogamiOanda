from __future__ import annotations

from pathlib import Path

import pytest

from tests.differential.compare import compare_traces
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


@pytest.mark.baseline_replay
@pytest.mark.slow
def test_legacy_capture_is_deterministic_for_analysis_seed():
    repo_root = Path(__file__).resolve().parents[2]
    scenario = next(item for item in load_all_scenarios() if item.scenario_id == "analysis-order-usd-jpy")

    matched, first_sha, second_sha = verify_trace_reproducibility(repo_root=repo_root, scenario=scenario)

    assert matched is True
    assert first_sha == second_sha


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
