"""Ownership and compatibility contracts for independently selectable strategies."""

import ast
import importlib
from pathlib import Path

import pytest

STRATEGY_ROOT = Path(__file__).parents[2] / "src" / "ogami_oanda" / "strategy"


@pytest.mark.contract
@pytest.mark.parametrize(("legacy", "canonical"), [
    ("contracts", "shared.contracts"),
    ("loader", "shared.loader"),
    ("line", "original.line"),
    ("line.builder", "original.line.builder"),
    ("line.usd_jpy", "original.line.usd_jpy"),
    ("position_sizing", "original.position_sizing"),
    ("position_management", "shared.position_management"),
    ("position_management.entry_confirmation", "shared.position_management.entry_confirmation"),
])
def test_legacy_imports_resolve_to_the_same_module_objects(legacy, canonical):
    canonical_module = importlib.import_module(f"ogami_oanda.strategy.{canonical}")
    legacy_module = importlib.import_module(f"ogami_oanda.strategy.{legacy}")
    assert legacy_module is canonical_module


@pytest.mark.contract
@pytest.mark.parametrize(("owner", "forbidden"), [
    ("original", ("matcha",)),
    ("matcha", ("original",)),
    ("shared", ("original", "matcha")),
])
def test_strategy_owners_do_not_import_other_strategies(owner, forbidden):
    directory = STRATEGY_ROOT / owner
    assert directory.is_dir()
    violations = []
    for path in directory.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        package = ("ogami_oanda", "strategy", *path.relative_to(STRATEGY_ROOT).parts[:-1])
        for node in ast.walk(tree):
            modules = []
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                base = node.module or ""
                if node.level:
                    base = ".".join((*package[:len(package) - node.level + 1], *base.split("."))).rstrip(".")
                modules = [base, *(f"{base}.{alias.name}" for alias in node.names)]
            for module in modules:
                if any(module == f"ogami_oanda.strategy.{other}" or module.startswith(f"ogami_oanda.strategy.{other}.") for other in forbidden):
                    violations.append(f"{path.relative_to(STRATEGY_ROOT)} imports {module}")
    assert not violations, "\n".join(violations)


@pytest.mark.contract
def test_original_offline_startup_does_not_import_unselected_matcha():
    import os
    import subprocess
    import sys

    program = '''
import importlib.abc
import sys

class RejectMatcha(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.startswith("ogami_oanda.strategy.matcha"):
            raise AssertionError("original startup must not execute unselected Matcha")
        return None

sys.meta_path.insert(0, RejectMatcha())
from ogami_oanda.entrypoints.live import main
assert main(["--strategy", "original", "--offline-smoke", "--dry-run", "--once"]) == 0
assert not any(name.startswith("ogami_oanda.strategy.matcha") for name in sys.modules)
'''
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(STRATEGY_ROOT.parents[1])
    result = subprocess.run(
        [sys.executable, "-c", program], env=environment,
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr
