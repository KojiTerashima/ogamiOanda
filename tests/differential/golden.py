from __future__ import annotations

import hashlib
import json
import platform
from pathlib import Path
from typing import Any

import numpy
import pandas

from .constants import BASELINE_COMMIT, BASELINE_TREE, GOLDEN_ROOT, TRACE_SCHEMA_VERSION
from .scenario import DifferentialScenario
from .trace import canonical_json_bytes

MANIFEST_FILE = "manifest.json"


def golden_trace_path(scenario_id: str) -> Path:
    return GOLDEN_ROOT / f"{scenario_id}.trace.json"


def write_golden_trace(scenario_id: str, trace: dict[str, Any]) -> Path:
    path = golden_trace_path(scenario_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_json_bytes(trace))
    return path


def load_golden_trace(scenario_id: str) -> dict[str, Any]:
    path = golden_trace_path(scenario_id)
    if not path.exists():
        raise FileNotFoundError(f"Golden trace missing: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def manifest_path() -> Path:
    return GOLDEN_ROOT / MANIFEST_FILE


def load_manifest() -> dict[str, Any]:
    path = manifest_path()
    if not path.exists():
        raise FileNotFoundError(f"manifest missing: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def build_manifest(
    *,
    scenarios: list[DifferentialScenario],
    traces: dict[str, dict[str, Any]],
    runner_files: list[Path],
) -> dict[str, Any]:
    scenario_map = {
        scenario.scenario_id: {
            "scenario_file": scenario_file_name(scenario),
            "scenario_sha256": hashlib.sha256(canonical_json_bytes(scenario.payload)).hexdigest(),
            "trace_file": f"{scenario.scenario_id}.trace.json",
            "trace_sha256": hashlib.sha256(canonical_json_bytes(traces[scenario.scenario_id])).hexdigest(),
        }
        for scenario in scenarios
    }

    return {
        "baseline_commit": BASELINE_COMMIT,
        "baseline_tree": BASELINE_TREE,
        "trace_schema_version": TRACE_SCHEMA_VERSION,
        "python_version": platform.python_version(),
        "package_versions": {
            "pandas": pandas.__version__,
            "numpy": numpy.__version__,
        },
        "runner_sha256": {
            str(path.relative_to(Path.cwd())): file_sha256(path)
            for path in runner_files
        },
        "scenarios": scenario_map,
    }


def write_manifest(manifest: dict[str, Any]) -> Path:
    path = manifest_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    return path


def scenario_file_name(scenario: DifferentialScenario) -> str:
    return f"{scenario.scenario_id}.json"


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
