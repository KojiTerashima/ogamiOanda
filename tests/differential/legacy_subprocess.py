from __future__ import annotations

# ruff: noqa: E402

import argparse
import importlib.abc
import json
import os
import sys
import types
from pathlib import Path

WORKSPACE_ROOT = Path(__file__).resolve().parents[2]


class _CurrentProductionImportBlocker(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        del path, target
        if fullname == "ogami_oanda" or fullname.startswith("ogami_oanda."):
            raise ImportError(
                "current ogami_oanda imports are prohibited in legacy replay"
            )
        return None


def _install_test_package() -> None:
    tests_root = WORKSPACE_ROOT / "tests"
    differential_root = tests_root / "differential"
    tests_package = types.ModuleType("tests")
    tests_package.__path__ = [str(tests_root)]
    differential_package = types.ModuleType("tests.differential")
    differential_package.__path__ = [str(differential_root)]
    sys.modules["tests"] = tests_package
    sys.modules["tests.differential"] = differential_package


sys.meta_path.insert(0, _CurrentProductionImportBlocker())
_install_test_package()

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
    current_root = str(WORKSPACE_ROOT.resolve())
    current_src = str((WORKSPACE_ROOT / "src").resolve())
    filtered = [
        entry
        for entry in sys.path
        if entry not in {cwd, current_root, current_src}
    ]
    sys.path[:] = [cwd, *filtered]


def _assert_no_current_production_modules() -> None:
    current_src = (WORKSPACE_ROOT / "src").resolve()
    for name, module in sys.modules.items():
        module_file = getattr(module, "__file__", None)
        if not module_file:
            continue
        path = Path(module_file).resolve()
        if path == current_src or current_src in path.parents:
            raise RuntimeError(
                f"legacy replay imported current production module {name}: {path}"
            )


def _assert_current_production_import_is_blocked() -> None:
    try:
        __import__("ogami_oanda")
    except ImportError as error:
        if "prohibited in legacy replay" not in str(error):
            raise RuntimeError(
                f"unexpected ogami_oanda import failure: {error}"
            ) from error
        return
    raise RuntimeError("legacy replay can import current ogami_oanda")


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    expected_worktree = Path(args.expected_worktree).resolve()
    _assert_running_inside_expected_worktree(expected_worktree)
    _prioritize_cwd_imports()
    _assert_current_production_import_is_blocked()

    # Ensure current workspace src is not available via environment leakage.
    os.environ.pop("PYTHONPATH", None)
    os.environ["PYTHONDONTWRITEBYTECODE"] = "1"

    scenario_path = Path(args.scenario).resolve()
    output_path = Path(args.output).resolve()
    log_path = Path(args.log).resolve()

    scenario = load_scenario_file(scenario_path)
    os.environ["LEGACY_EXPECTED_WORKTREE"] = str(expected_worktree)

    run_legacy_scenario_to_path(scenario, output_path=output_path, log_path=log_path)
    _assert_no_current_production_modules()

    # Validate trace is parseable json before returning success.
    json.loads(output_path.read_text(encoding="utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
