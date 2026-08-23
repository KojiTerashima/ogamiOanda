from __future__ import annotations

# ruff: noqa: E402

import argparse
import json
import sys
from pathlib import Path

WORKSPACE_ROOT = Path(__file__).resolve().parents[2]
if str(WORKSPACE_ROOT) not in sys.path:
    sys.path.insert(0, str(WORKSPACE_ROOT))

from tests.differential.compare import compare_traces, load_allowlist, save_failure_artifacts
from tests.differential.constants import BASELINE_COMMIT, GOLDEN_ROOT
from tests.differential.current_runner import run_current_scenario
from tests.differential.golden import (
    build_manifest,
    load_golden_trace,
    write_golden_trace,
    write_manifest,
)
from tests.differential.orchestrator import capture_legacy_trace
from tests.differential.scenario import load_all_scenarios, select_scenarios
from tests.differential.trace import canonical_sha256, ensure_trace_envelope
from tests.differential.worktree import verify_baseline_reference


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Differential legacy/current verification utilities")
    subparsers = parser.add_subparsers(dest="command", required=True)

    def add_selection_flags(command_parser: argparse.ArgumentParser) -> None:
        command_parser.add_argument("--scenario-id", action="append", default=[], help="Scenario id to run (repeatable)")
        command_parser.add_argument("--all", action="store_true", help="Run all scenarios")

    capture = subparsers.add_parser("capture-legacy", help="Capture legacy traces into an output folder")
    add_selection_flags(capture)
    capture.add_argument("--out", default="build/differential/captured-legacy", help="Output directory for captured traces")

    verify = subparsers.add_parser("verify-baseline", help="Re-capture legacy baseline and verify against checked-in golden")
    add_selection_flags(verify)
    verify.add_argument("--legacy-ref", required=True, help="Must match exact baseline commit SHA")

    compare = subparsers.add_parser("compare-current", help="Compare current runner with checked-in golden traces")
    add_selection_flags(compare)

    update = subparsers.add_parser("update-golden", help="Update checked-in golden traces from legacy baseline")
    add_selection_flags(update)
    update.add_argument("--legacy-ref", required=True, help="Must match exact baseline commit SHA")
    update.add_argument("--confirm-baseline-sha", required=True, help="Explicit confirmation SHA guard")

    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    repo_root = Path(__file__).resolve().parents[2]
    scenarios = load_all_scenarios()
    selected = select_scenarios(scenarios, scenario_ids=args.scenario_id, include_all=args.all)

    if args.command == "capture-legacy":
        return _capture_legacy(repo_root, selected, Path(args.out))
    if args.command == "verify-baseline":
        _require_exact_baseline_ref(args.legacy_ref)
        return _verify_baseline(repo_root, selected)
    if args.command == "compare-current":
        return _compare_current(selected)
    if args.command == "update-golden":
        _require_exact_baseline_ref(args.legacy_ref)
        if args.confirm_baseline_sha != BASELINE_COMMIT:
            raise SystemExit(
                f"--confirm-baseline-sha must be exact baseline SHA {BASELINE_COMMIT}"
            )
        return _update_golden(repo_root, selected)

    raise SystemExit(f"Unsupported command: {args.command}")


def _capture_legacy(repo_root: Path, selected, out_dir: Path) -> int:
    verify_baseline_reference(repo_root)
    out_dir.mkdir(parents=True, exist_ok=True)
    for scenario in selected:
        captured = capture_legacy_trace(repo_root=repo_root, scenario=scenario)
        path = out_dir / f"{scenario.scenario_id}.trace.json"
        path.write_text(json.dumps(captured.trace, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
        (out_dir / f"{scenario.scenario_id}.legacy.log.txt").write_text(captured.legacy_log, encoding="utf-8")
        print(f"captured {scenario.scenario_id} sha256={captured.trace_sha256}")
    return 0


def _verify_baseline(repo_root: Path, selected) -> int:
    verify_baseline_reference(repo_root)
    failures = 0

    for scenario in selected:
        captured = capture_legacy_trace(repo_root=repo_root, scenario=scenario)
        golden = load_golden_trace(scenario.scenario_id)
        compare_result = compare_traces(
            scenario_id=scenario.scenario_id,
            baseline_trace=golden,
            current_trace=captured.trace,
            allowlist_entries=[],
        )
        if not compare_result.matched:
            artifact_dir = save_failure_artifacts(
                scenario_id=scenario.scenario_id,
                baseline_trace=golden,
                current_trace=captured.trace,
                compare_result=compare_result,
                legacy_log=captured.legacy_log,
            )
            failures += 1
            print(f"baseline mismatch: {scenario.scenario_id} -> {artifact_dir}")
        else:
            print(f"baseline ok: {scenario.scenario_id} sha256={captured.trace_sha256}")

    return 1 if failures else 0


def _compare_current(selected) -> int:
    allowlist = load_allowlist()
    failures = 0

    for scenario in selected:
        golden = load_golden_trace(scenario.scenario_id)
        current_raw = run_current_scenario(scenario).trace
        current_trace = ensure_trace_envelope(current_raw, scenario_id=scenario.scenario_id, runner="current")
        compare_result = compare_traces(
            scenario_id=scenario.scenario_id,
            baseline_trace=golden,
            current_trace=current_trace,
            allowlist_entries=allowlist,
        )
        if not compare_result.matched:
            artifact_dir = save_failure_artifacts(
                scenario_id=scenario.scenario_id,
                baseline_trace=golden,
                current_trace=current_trace,
                compare_result=compare_result,
            )
            failures += 1
            reason = "stale allowlist" if compare_result.mismatch is None else compare_result.mismatch.pointer
            print(f"current mismatch: {scenario.scenario_id} ({reason}) -> {artifact_dir}")
        else:
            print(f"current ok: {scenario.scenario_id} sha256={canonical_sha256(current_trace)}")

    return 1 if failures else 0


def _update_golden(repo_root: Path, selected) -> int:
    verify_baseline_reference(repo_root)
    traces = {}
    for scenario in selected:
        captured = capture_legacy_trace(repo_root=repo_root, scenario=scenario)
        traces[scenario.scenario_id] = captured.trace
        write_golden_trace(scenario.scenario_id, captured.trace)
        print(f"updated golden: {scenario.scenario_id} sha256={captured.trace_sha256}")

    runner_files = [
        Path(__file__).resolve(),
        (Path(__file__).resolve().parent / "legacy_runner.py"),
        (Path(__file__).resolve().parent / "legacy_subprocess.py"),
        (Path(__file__).resolve().parent / "current_runner.py"),
        (Path(__file__).resolve().parent / "normalize.py"),
        (Path(__file__).resolve().parent / "compare.py"),
        (Path(__file__).resolve().parent / "scenario.py"),
        (Path(__file__).resolve().parent / "orchestrator.py"),
    ]
    manifest = build_manifest(scenarios=selected, traces=traces, runner_files=runner_files)
    write_manifest(manifest)
    print(f"manifest updated: {GOLDEN_ROOT / 'manifest.json'}")
    return 0


def _require_exact_baseline_ref(value: str) -> None:
    if value != BASELINE_COMMIT:
        raise SystemExit(f"legacy ref must be exact baseline SHA: {BASELINE_COMMIT}")


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
