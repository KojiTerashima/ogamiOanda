from __future__ import annotations

import json
import os
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .compare import (
    CompareResult,
    compare_traces,
    load_allowlist,
    save_failure_artifacts,
    traces_byte_equal,
)
from .constants import BASELINE_COMMIT
from .current_runner import run_current_scenario
from .normalize import normalize_trace
from .scenario import DifferentialScenario
from .trace import canonical_sha256, ensure_trace_envelope
from .worktree import baseline_worktree


@dataclass(frozen=True)
class ScenarioRunArtifacts:
    scenario_id: str
    legacy_trace: dict[str, Any]
    current_trace: dict[str, Any]
    compare_result: CompareResult
    artifact_dir: Path | None
    legacy_log: str


@dataclass(frozen=True)
class BaselineCaptureItem:
    scenario_id: str
    trace: dict[str, Any]
    trace_sha256: str
    legacy_log: str


def compare_current_with_legacy(
    *,
    repo_root: Path,
    scenario: DifferentialScenario,
    allowlist_path: Path | None = None,
) -> ScenarioRunArtifacts:
    legacy_raw, legacy_log = _run_legacy_in_isolated_worktree(repo_root=repo_root, scenario=scenario)
    current_raw = run_current_scenario(scenario).trace

    legacy_trace = ensure_trace_envelope(legacy_raw, scenario_id=scenario.scenario_id, runner="legacy")
    current_trace = ensure_trace_envelope(current_raw, scenario_id=scenario.scenario_id, runner="current")

    allowlist_entries = load_allowlist(allowlist_path)
    compare_result = compare_traces(
        scenario_id=scenario.scenario_id,
        baseline_trace=legacy_trace,
        current_trace=current_trace,
        allowlist_entries=allowlist_entries,
    )

    artifact_dir: Path | None = None
    if not compare_result.matched:
        artifact_dir = save_failure_artifacts(
            scenario_id=scenario.scenario_id,
            baseline_trace=legacy_trace,
            current_trace=current_trace,
            compare_result=compare_result,
            legacy_log=legacy_log,
        )

    return ScenarioRunArtifacts(
        scenario_id=scenario.scenario_id,
        legacy_trace=legacy_trace,
        current_trace=current_trace,
        compare_result=compare_result,
        artifact_dir=artifact_dir,
        legacy_log=legacy_log,
    )


def capture_legacy_trace(
    *,
    repo_root: Path,
    scenario: DifferentialScenario,
) -> BaselineCaptureItem:
    legacy_raw, legacy_log = _run_legacy_in_isolated_worktree(repo_root=repo_root, scenario=scenario)
    trace = ensure_trace_envelope(legacy_raw, scenario_id=scenario.scenario_id, runner="legacy")
    normalized = normalize_trace(trace)
    return BaselineCaptureItem(
        scenario_id=scenario.scenario_id,
        trace=normalized,
        trace_sha256=canonical_sha256(normalized),
        legacy_log=legacy_log,
    )


def verify_trace_reproducibility(
    *,
    repo_root: Path,
    scenario: DifferentialScenario,
) -> tuple[bool, str, str]:
    first = capture_legacy_trace(repo_root=repo_root, scenario=scenario)
    second = capture_legacy_trace(repo_root=repo_root, scenario=scenario)
    return traces_byte_equal(first.trace, second.trace), first.trace_sha256, second.trace_sha256


def _run_legacy_in_isolated_worktree(*, repo_root: Path, scenario: DifferentialScenario) -> tuple[dict[str, Any], str]:
    with baseline_worktree(repo_root, commit=BASELINE_COMMIT) as wt:
        with tempfile.TemporaryDirectory(prefix="ogami-diff-run-") as tmp_dir:
            tmp_path = Path(tmp_dir)
            scenario_path = tmp_path / "scenario.json"
            output_path = tmp_path / "trace.json"
            log_path = tmp_path / "legacy.log"

            scenario_path.write_text(json.dumps(scenario.payload, ensure_ascii=True), encoding="utf-8")

            command = [
                sys_executable(repo_root),
                str(repo_root / "tests" / "differential" / "legacy_subprocess.py"),
                "--scenario",
                str(scenario_path),
                "--output",
                str(output_path),
                "--log",
                str(log_path),
                "--expected-worktree",
                str(wt.worktree_path),
            ]

            env = os.environ.copy()
            env.pop("PYTHONPATH", None)
            env["PYTHONDONTWRITEBYTECODE"] = "1"

            completed = subprocess.run(
                command,
                cwd=str(wt.worktree_path),
                env=env,
                check=False,
                capture_output=True,
                text=True,
                timeout=120,
            )
            if completed.returncode != 0:
                raise RuntimeError(
                    "legacy subprocess failed\n"
                    f"stdout:\n{completed.stdout}\n"
                    f"stderr:\n{completed.stderr}"
                )

            trace = json.loads(output_path.read_text(encoding="utf-8"))
            log = log_path.read_text(encoding="utf-8") if log_path.exists() else ""
            return trace, log


def sys_executable(repo_root: Path) -> str:
    candidate = repo_root / ".venv" / "bin" / "python"
    if candidate.exists():
        return str(candidate)
    return os.environ.get("PYTHON", "python3")
