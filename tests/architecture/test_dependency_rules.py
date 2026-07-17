import ast
from pathlib import Path

import pytest

SOURCE_ROOT = Path(__file__).parents[2] / "src" / "ogami_oanda"
FORBIDDEN_MODULES = {"tokens", "requests", "oandapyV20"}


@pytest.mark.contract
@pytest.mark.parametrize("package", ["domain", "strategy"])
def test_domain_and_strategy_do_not_depend_on_adapters_or_external_io(package):
    violations = []
    for path in (SOURCE_ROOT / package).rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                modules = [node.module or ""]
            else:
                continue
            for module in modules:
                root = module.split(".")[0]
                if root in FORBIDDEN_MODULES or module.startswith("ogami_oanda.adapters") or module.startswith("ogami_oanda.infrastructure"):
                    violations.append(f"{path.relative_to(SOURCE_ROOT)} imports {module}")
    assert not violations, "\n".join(violations)
