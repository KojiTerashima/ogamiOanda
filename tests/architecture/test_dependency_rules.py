import ast
from pathlib import Path

import pytest

SOURCE_ROOT = Path(__file__).parents[2] / "src" / "ogami_oanda"
FORBIDDEN_MODULES = {"tokens", "requests", "oandapyV20"}
ROOT_LEGACY_MODULES = {
    "classOanda",
    "classPosition",
    "classPositionControl",
    "classOrderCreate",
    "fAnalysis_order_Main",
    "fGeneric",
    "fLineAnalysis",
    "main_exe",
    "send_notice",
    "tokens",
}


def _imports(path: Path):
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            yield from (alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            yield node.module or ""


@pytest.mark.contract
@pytest.mark.parametrize("package", ["domain", "strategy"])
def test_domain_and_strategy_do_not_depend_on_adapters_or_external_io(package):
    violations = []
    for path in (SOURCE_ROOT / package).rglob("*.py"):
        for module in _imports(path):
            root = module.split(".")[0]
            if root in FORBIDDEN_MODULES or module.startswith("ogami_oanda.adapters") or module.startswith("ogami_oanda.infrastructure"):
                violations.append(f"{path.relative_to(SOURCE_ROOT)} imports {module}")
    assert not violations, "\n".join(violations)


@pytest.mark.contract
def test_src_has_no_root_legacy_imports():
    violations = []
    for path in SOURCE_ROOT.rglob("*.py"):
        for module in _imports(path):
            if module.split(".")[0] in ROOT_LEGACY_MODULES:
                violations.append(f"{path.relative_to(SOURCE_ROOT)} imports {module}")
    assert not violations, "\n".join(violations)


@pytest.mark.contract
def test_external_io_dependencies_are_confined_to_their_adapters():
    violations = []
    for path in SOURCE_ROOT.rglob("*.py"):
        relative = path.relative_to(SOURCE_ROOT)
        for module in _imports(path):
            root = module.split(".")[0]
            if root == "oandapyV20" and relative.parts[:2] != ("adapters", "oanda"):
                violations.append(f"{relative} imports {module}")
            if root == "requests" and relative.parts[:2] != ("adapters", "notifications"):
                violations.append(f"{relative} imports {module}")
            if root == "tokens" and relative.parts[:2] != ("adapters", "legacy"):
                violations.append(f"{relative} imports {module}")
    assert not violations, "\n".join(violations)
