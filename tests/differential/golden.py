from __future__ import annotations

import hashlib
import json
import platform
from pathlib import Path
from typing import Any

import numpy
import pandas

from .constants import (
    BASELINE_COMMIT,
    BASELINE_TREE,
    GOLDEN_ROOT,
    SCENARIO_ROOT,
    TRACE_SCHEMA_VERSION,
)
from .scenario import DifferentialScenario
from .trace import canonical_json_bytes, ensure_trace_envelope

MANIFEST_FILE = "manifest.json"
_MANIFEST_KEYS = {
    "baseline_commit",
    "baseline_tree",
    "trace_schema_version",
    "python_version",
    "package_versions",
    "runner_sha256",
    "scenarios",
}
_PACKAGE_VERSION_KEYS = {"pandas", "numpy"}
_SCENARIO_ENTRY_KEYS = {
    "scenario_file",
    "scenario_sha256",
    "materialized_input_sha256",
    "trace_file",
    "trace_sha256",
}


class GoldenManifestError(ValueError):
    pass


def golden_trace_path(scenario_id: str) -> Path:
    return GOLDEN_ROOT / f"{scenario_id}.trace.json"


def write_golden_trace(scenario_id: str, trace: dict[str, Any]) -> Path:
    path = golden_trace_path(scenario_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(canonical_json_bytes(trace))
    tmp.replace(path)
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
            "scenario_sha256": file_sha256(
                SCENARIO_ROOT / scenario_file_name(scenario)
            ),
            "materialized_input_sha256": hashlib.sha256(
                canonical_json_bytes(scenario.payload)
            ).hexdigest(),
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


def provenance_runner_files() -> list[Path]:
    root = Path(__file__).resolve().parent
    return [
        root / name
        for name in (
            "baseline_contract.json",
            "bootstrap.py",
            "cli.py",
            "constants.py",
            "legacy_runner.py",
            "legacy_subprocess.py",
            "current_runner.py",
            "analysis_trace.py",
            "frame_factory.py",
            "golden.py",
            "normalize.py",
            "offline.py",
            "compare.py",
            "scenario.py",
            "orchestrator.py",
            "scripted_broker.py",
            "trace.py",
            "worktree.py",
        )
    ]


def verify_checked_in_manifest(
    *,
    scenarios: list[DifferentialScenario],
    runner_files: list[Path] | None = None,
    manifest: dict[str, Any] | None = None,
    trace_root: Path | None = None,
) -> None:
    actual = manifest or load_manifest()
    if set(actual) != _MANIFEST_KEYS:
        raise GoldenManifestError(
            "manifest keys mismatch: "
            f"expected {sorted(_MANIFEST_KEYS)}, got {sorted(actual)}"
        )
    expected_identity = {
        "baseline_commit": BASELINE_COMMIT,
        "baseline_tree": BASELINE_TREE,
        "trace_schema_version": TRACE_SCHEMA_VERSION,
        "python_version": platform.python_version(),
    }
    for key, expected in expected_identity.items():
        if actual.get(key) != expected:
            raise GoldenManifestError(
                f"manifest {key} mismatch: expected {expected}, got {actual.get(key)}"
            )

    package_versions = actual.get("package_versions")
    if not isinstance(package_versions, dict) or set(package_versions) != _PACKAGE_VERSION_KEYS:
        raise GoldenManifestError("manifest package_versions schema mismatch")
    expected_package_versions = {
        "pandas": pandas.__version__,
        "numpy": numpy.__version__,
    }
    if package_versions != expected_package_versions:
        raise GoldenManifestError(
            "manifest package_versions mismatch: "
            f"expected {expected_package_versions}, got {package_versions}"
        )

    files = runner_files or provenance_runner_files()
    expected_runner_hashes = {
        str(path.relative_to(Path.cwd())): file_sha256(path)
        for path in files
    }
    if actual.get("runner_sha256") != expected_runner_hashes:
        raise GoldenManifestError("manifest runner_sha256 does not match runner files")

    scenario_entries = actual.get("scenarios")
    if not isinstance(scenario_entries, dict):
        raise GoldenManifestError("manifest scenarios must be an object")
    expected_ids = {scenario.scenario_id for scenario in scenarios}
    if set(scenario_entries) != expected_ids:
        raise GoldenManifestError("manifest scenario ids do not match scenario files")

    for scenario in scenarios:
        entry = scenario_entries[scenario.scenario_id]
        if not isinstance(entry, dict) or set(entry) != _SCENARIO_ENTRY_KEYS:
            raise GoldenManifestError(
                f"manifest scenario schema mismatch for {scenario.scenario_id}"
            )
        expected_scenario_hash = file_sha256(
            SCENARIO_ROOT / scenario_file_name(scenario)
        )
        expected_input_hash = hashlib.sha256(
            canonical_json_bytes(scenario.payload)
        ).hexdigest()
        if entry.get("scenario_file") != scenario_file_name(scenario):
            raise GoldenManifestError(
                f"manifest scenario_file mismatch for {scenario.scenario_id}"
            )
        if entry.get("scenario_sha256") != expected_scenario_hash:
            raise GoldenManifestError(
                f"manifest scenario_sha256 mismatch for {scenario.scenario_id}"
            )
        if entry.get("materialized_input_sha256") != expected_input_hash:
            raise GoldenManifestError(
                f"manifest materialized_input_sha256 mismatch for {scenario.scenario_id}"
            )
        expected_trace_file = f"{scenario.scenario_id}.trace.json"
        if entry.get("trace_file") != expected_trace_file:
            raise GoldenManifestError(
                f"manifest trace_file mismatch for {scenario.scenario_id}"
            )
        root = (trace_root or GOLDEN_ROOT).resolve()
        trace_file = (root / expected_trace_file).resolve()
        if trace_file.parent != root:
            raise GoldenManifestError(
                f"manifest trace path escapes golden root for {scenario.scenario_id}"
            )
        if not trace_file.is_file():
            raise GoldenManifestError(
                f"manifest trace missing for {scenario.scenario_id}: {trace_file}"
            )
        trace_bytes = trace_file.read_bytes()
        try:
            trace = json.loads(trace_bytes)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise GoldenManifestError(
                f"manifest trace is not valid JSON for {scenario.scenario_id}"
            ) from error
        if not isinstance(trace, dict):
            raise GoldenManifestError(
                f"manifest trace must be an object for {scenario.scenario_id}"
            )
        try:
            ensure_trace_envelope(
                trace,
                scenario_id=scenario.scenario_id,
                runner="trace-runner",
            )
        except ValueError as error:
            raise GoldenManifestError(
                f"manifest trace envelope mismatch for {scenario.scenario_id}: {error}"
            ) from error
        if trace_bytes != canonical_json_bytes(trace):
            raise GoldenManifestError(
                f"manifest trace is not canonical JSON for {scenario.scenario_id}"
            )
        expected_trace_hash = hashlib.sha256(trace_bytes).hexdigest()
        if entry.get("trace_sha256") != expected_trace_hash:
            raise GoldenManifestError(
                f"manifest trace_sha256 mismatch for {scenario.scenario_id}"
            )


def write_manifest(manifest: dict[str, Any]) -> Path:
    path = manifest_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )
    tmp.replace(path)
    return path


def scenario_file_name(scenario: DifferentialScenario) -> str:
    return f"{scenario.scenario_id}.json"


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
