from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .constants import ALLOWLIST_PATH, ARTIFACT_ROOT
from .normalize import normalize_trace
from .trace import canonical_json_bytes, canonical_sha256, write_trace_atomic


@dataclass(frozen=True)
class DiffMismatch:
    pointer: str
    left: Any
    right: Any
    message: str


@dataclass(frozen=True)
class AllowlistEntry:
    delta_id: str
    scenario_id: str
    pointer: str
    left: Any
    right: Any
    reason: str
    reference: str
    expires_on: str


@dataclass(frozen=True)
class CompareResult:
    matched: bool
    mismatch: DiffMismatch | None
    allowlist_applied: AllowlistEntry | None
    stale_entries: tuple[AllowlistEntry, ...]


class CompareError(ValueError):
    pass


def compare_traces(
    *,
    scenario_id: str,
    baseline_trace: dict[str, Any],
    current_trace: dict[str, Any],
    allowlist_entries: list[AllowlistEntry],
) -> CompareResult:
    baseline = normalize_trace(baseline_trace)
    current = normalize_trace(current_trace)

    mismatch = _first_mismatch(baseline, current, pointer="")
    if mismatch is None:
        stale = tuple(entry for entry in allowlist_entries if entry.scenario_id == scenario_id)
        return CompareResult(matched=len(stale) == 0, mismatch=None, allowlist_applied=None, stale_entries=stale)

    matched_entry = _match_allowlist_entry(scenario_id, mismatch, allowlist_entries)
    if matched_entry is None:
        return CompareResult(matched=False, mismatch=mismatch, allowlist_applied=None, stale_entries=())

    stale = tuple(
        entry
        for entry in allowlist_entries
        if entry.scenario_id == scenario_id and entry.delta_id != matched_entry.delta_id
    )
    return CompareResult(matched=len(stale) == 0, mismatch=mismatch, allowlist_applied=matched_entry, stale_entries=stale)


def load_allowlist(path: Path | None = None) -> list[AllowlistEntry]:
    file_path = path or ALLOWLIST_PATH
    if not file_path.exists():
        return []
    raw = json.loads(file_path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise CompareError("Allowlist must be a list")

    result = []
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            raise CompareError(f"Allowlist entry at index {index} must be object")
        required = {
            "delta_id",
            "scenario_id",
            "pointer",
            "left",
            "right",
            "reason",
            "reference",
            "expires_on",
        }
        missing = sorted(required - set(item))
        if missing:
            raise CompareError(f"Allowlist entry {index} missing keys: {missing}")
        if not item["scenario_id"]:
            raise CompareError(f"Allowlist entry {index}: scenario_id must be non-empty")
        if "*" in str(item["pointer"]):
            raise CompareError(f"Allowlist entry {index}: wildcard pointer is not allowed")
        result.append(
            AllowlistEntry(
                delta_id=str(item["delta_id"]),
                scenario_id=str(item["scenario_id"]),
                pointer=str(item["pointer"]),
                left=item["left"],
                right=item["right"],
                reason=str(item["reason"]),
                reference=str(item["reference"]),
                expires_on=str(item["expires_on"]),
            )
        )
    return result


def save_failure_artifacts(
    *,
    scenario_id: str,
    baseline_trace: dict[str, Any],
    current_trace: dict[str, Any],
    compare_result: CompareResult,
    legacy_log: str | None = None,
) -> Path:
    output_dir = ARTIFACT_ROOT / scenario_id
    output_dir.mkdir(parents=True, exist_ok=True)

    write_trace_atomic(output_dir / "legacy.trace.json", normalize_trace(baseline_trace))
    write_trace_atomic(output_dir / "current.trace.json", normalize_trace(current_trace))

    diff_payload = {
        "matched": compare_result.matched,
        "mismatch": {
            "pointer": compare_result.mismatch.pointer,
            "left": compare_result.mismatch.left,
            "right": compare_result.mismatch.right,
            "message": compare_result.mismatch.message,
        }
        if compare_result.mismatch
        else None,
        "allowlist_applied": compare_result.allowlist_applied.delta_id if compare_result.allowlist_applied else None,
        "stale_entries": [entry.delta_id for entry in compare_result.stale_entries],
        "legacy_sha256": canonical_sha256(normalize_trace(baseline_trace)),
        "current_sha256": canonical_sha256(normalize_trace(current_trace)),
    }
    write_trace_atomic(output_dir / "diff.json", diff_payload)

    if legacy_log is not None:
        (output_dir / "legacy.log.txt").write_text(legacy_log, encoding="utf-8")

    return output_dir


def _first_mismatch(left: Any, right: Any, *, pointer: str) -> DiffMismatch | None:
    if type(left) is not type(right):
        return DiffMismatch(pointer or "/", left, right, f"type mismatch: {type(left).__name__} != {type(right).__name__}")

    if isinstance(left, dict):
        left_keys = list(left.keys())
        right_keys = list(right.keys())
        if left_keys != right_keys:
            return DiffMismatch(pointer or "/", left_keys, right_keys, "mapping keys differ")
        for key in left_keys:
            next_pointer = f"{pointer}/{_escape_pointer_segment(str(key))}" if pointer else f"/{_escape_pointer_segment(str(key))}"
            mismatch = _first_mismatch(left[key], right[key], pointer=next_pointer)
            if mismatch is not None:
                return mismatch
        return None

    if isinstance(left, list):
        if len(left) != len(right):
            return DiffMismatch(pointer or "/", len(left), len(right), "list length differs")
        for index, (left_item, right_item) in enumerate(zip(left, right)):
            next_pointer = f"{pointer}/{index}" if pointer else f"/{index}"
            mismatch = _first_mismatch(left_item, right_item, pointer=next_pointer)
            if mismatch is not None:
                return mismatch
        return None

    if left != right:
        return DiffMismatch(pointer or "/", left, right, "scalar value differs")
    return None


def _match_allowlist_entry(
    scenario_id: str,
    mismatch: DiffMismatch,
    entries: list[AllowlistEntry],
) -> AllowlistEntry | None:
    for entry in entries:
        if entry.scenario_id != scenario_id:
            continue
        if entry.pointer != mismatch.pointer:
            continue
        if entry.left != mismatch.left:
            continue
        if entry.right != mismatch.right:
            continue
        return entry
    return None


def _escape_pointer_segment(value: str) -> str:
    return value.replace("~", "~0").replace("/", "~1")


def traces_byte_equal(left: dict[str, Any], right: dict[str, Any]) -> bool:
    return canonical_json_bytes(normalize_trace(left)) == canonical_json_bytes(normalize_trace(right))
