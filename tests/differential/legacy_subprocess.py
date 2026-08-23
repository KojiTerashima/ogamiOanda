from __future__ import annotations

# ruff: noqa: E402

import argparse
import json
import os
import sys
from pathlib import Path

WORKSPACE_ROOT = Path(__file__).resolve().parents[2]
if str(WORKSPACE_ROOT) not in sys.path:
    sys.path.append(str(WORKSPACE_ROOT))

from tests.differential.legacy_runner import run_legacy_scenario_to_path
from tests.differential.scenario import load_scenario_file


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run one legacy differential scenario in isolated subprocess")
    parser.add_argument("--scenario", required=True, help="Path to scenario json")
    parser.add_argument("--output", required=True, help="Path to output trace json")
    parser.add_argument("--log", required=True, help="Path to output legacy log")
    parser.add_argument("--expected-worktree", required=True, help="Absolute path to expected legacy worktree")
    return parser.parse_args(argv)


def _assert_running_inside_expected_worktree(expected_worktree: Path) -> None:
    cwd = Path.cwd().resolve()
    if cwd != expected_worktree.resolve():
        raise RuntimeError(f"legacy subprocess cwd mismatch: expected {expected_worktree}, got {cwd}")

    if not (cwd / "main_exe.py").exists():
        raise RuntimeError("expected legacy baseline files are missing from cwd")

    if (cwd / "src" / "ogami_oanda").exists():
        raise RuntimeError("legacy subprocess cwd unexpectedly contains src/ogami_oanda")


def _prioritize_cwd_imports() -> None:
    cwd = str(Path.cwd().resolve())
    filtered = [entry for entry in sys.path if entry != cwd]
    sys.path[:] = [cwd, *filtered]


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    expected_worktree = Path(args.expected_worktree).resolve()
    _assert_running_inside_expected_worktree(expected_worktree)
    _prioritize_cwd_imports()

    # Ensure current workspace src is not available via environment leakage.
    os.environ.pop("PYTHONPATH", None)
    os.environ["PYTHONDONTWRITEBYTECODE"] = "1"

    scenario_path = Path(args.scenario).resolve()
    output_path = Path(args.output).resolve()
    log_path = Path(args.log).resolve()

    scenario = load_scenario_file(scenario_path)
    os.environ["LEGACY_EXPECTED_WORKTREE"] = str(expected_worktree)

    run_legacy_scenario_to_path(scenario, output_path=output_path, log_path=log_path)

    # Validate trace is parseable json before returning success.
    json.loads(output_path.read_text(encoding="utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
