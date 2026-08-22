import ast
from pathlib import Path

import pytest

SOURCE_ROOT = Path(__file__).parents[2] / "src" / "ogami_oanda"
PROJECT_ROOT = SOURCE_ROOT.parents[1]
FORBIDDEN_MODULES = {"tokens", "requests", "oandapyV20"}
ROOT_LEGACY_MODULES = {path.stem for path in PROJECT_ROOT.glob("*.py")}


def _imports(path: Path):
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    relative = path.relative_to(SOURCE_ROOT)
    current_package = ("ogami_oanda", *relative.parts[:-1])
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            yield from (alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                keep = len(current_package) - (node.level - 1)
                base = current_package[:keep]
                suffix = tuple((node.module or "").split(".")) if node.module else ()
                yield ".".join((*base, *suffix))
            else:
                yield node.module or ""


def _calls(path: Path):
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name):
            yield f"{node.func.value.id}.{node.func.attr}"
        elif isinstance(node.func, ast.Name):
            yield node.func.id


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


@pytest.mark.contract
def test_application_does_not_depend_on_adapters_or_infrastructure():
    violations = []
    for path in (SOURCE_ROOT / "application").rglob("*.py"):
        for module in _imports(path):
            if module.startswith(("ogami_oanda.adapters", "ogami_oanda.infrastructure")):
                violations.append(f"{path.relative_to(SOURCE_ROOT)} imports {module}")
    assert not violations, "\n".join(violations)


@pytest.mark.contract
def test_adapters_do_not_depend_on_infrastructure_configuration():
    violations = []
    for path in (SOURCE_ROOT / "adapters").rglob("*.py"):
        for module in _imports(path):
            if module.startswith("ogami_oanda.infrastructure"):
                violations.append(f"{path.relative_to(SOURCE_ROOT)} imports {module}")
    assert not violations, "\n".join(violations)


@pytest.mark.contract
@pytest.mark.parametrize(
    ("layer", "allowed_internal_prefixes"),
    [
        ("domain", ("ogami_oanda.domain",)),
        ("strategy", ("ogami_oanda.strategy", "ogami_oanda.domain")),
        (
            "application",
            ("ogami_oanda.application", "ogami_oanda.domain", "ogami_oanda.strategy"),
        ),
        (
            "adapters",
            ("ogami_oanda.adapters", "ogami_oanda.application", "ogami_oanda.domain"),
        ),
        (
            "infrastructure",
            ("ogami_oanda.infrastructure", "ogami_oanda.application"),
        ),
        (
            "backtest",
            (
                "ogami_oanda.backtest",
                "ogami_oanda.application",
                "ogami_oanda.domain",
                "ogami_oanda.strategy",
            ),
        ),
        (
            "entrypoints",
            (
                "ogami_oanda.entrypoints",
                "ogami_oanda.adapters",
                "ogami_oanda.application",
                "ogami_oanda.domain",
                "ogami_oanda.infrastructure",
                "ogami_oanda.strategy",
            ),
        ),
    ],
)
def test_internal_dependency_matrix_points_toward_business_layers(layer, allowed_internal_prefixes):
    violations = []
    for path in (SOURCE_ROOT / layer).rglob("*.py"):
        for module in _imports(path):
            if module.startswith("ogami_oanda") and not module.startswith(allowed_internal_prefixes):
                violations.append(f"{path.relative_to(SOURCE_ROOT)} imports {module}")
    assert not violations, "\n".join(violations)


@pytest.mark.contract
def test_production_code_never_imports_test_layer():
    violations = []
    for path in SOURCE_ROOT.rglob("*.py"):
        for module in _imports(path):
            if module.split(".")[0] in {"tests", "pytest"}:
                violations.append(f"{path.relative_to(SOURCE_ROOT)} imports {module}")
    assert not violations, "\n".join(violations)


@pytest.mark.contract
def test_wall_clock_and_loop_sleep_are_confined_to_runtime_infrastructure():
    violations = []
    for path in SOURCE_ROOT.rglob("*.py"):
        relative = path.relative_to(SOURCE_ROOT)
        is_runtime = relative.parts[:2] == ("infrastructure", "runtime")
        for module in _imports(path):
            if module == "time" and not is_runtime:
                violations.append(f"{relative} imports {module}")
        for call in _calls(path):
            if call in {"time.sleep", "time.monotonic", "datetime.now"} and not is_runtime:
                violations.append(f"{relative} calls {call}")
    assert not violations, "\n".join(violations)


@pytest.mark.contract
def test_wall_clock_and_sleep_runtime_are_confined_to_infrastructure_runtime():
    violations = []
    for path in SOURCE_ROOT.rglob("*.py"):
        relative = path.relative_to(SOURCE_ROOT)
        for module in _imports(path):
            if module == "time" and relative.parts[:2] != ("infrastructure", "runtime"):
                violations.append(f"{relative} imports {module}")
    assert not violations, "\n".join(violations)
