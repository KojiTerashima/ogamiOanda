from __future__ import annotations

import pytest

from tests.differential.compare import compare_traces, load_allowlist
from tests.differential.current_runner import run_current_scenario
from tests.differential.golden import load_golden_trace
from tests.differential.scenario import load_all_scenarios
from tests.differential.trace import ensure_trace_envelope


@pytest.mark.contract
def test_current_runner_matches_checked_in_golden_traces():
    allowlist = load_allowlist()
    scenarios = load_all_scenarios()

    failures: list[str] = []
    for scenario in scenarios:
        golden = load_golden_trace(scenario.scenario_id)
        current = ensure_trace_envelope(
            run_current_scenario(scenario).trace,
            scenario_id=scenario.scenario_id,
            runner="current",
        )
        result = compare_traces(
            scenario_id=scenario.scenario_id,
            baseline_trace=golden,
            current_trace=current,
            allowlist_entries=allowlist,
        )
        if not result.matched:
            if result.mismatch is None:
                failures.append(f"{scenario.scenario_id}: stale_allowlist")
            else:
                failures.append(f"{scenario.scenario_id}: {result.mismatch.pointer}")

    assert not failures, "\n".join(failures)
