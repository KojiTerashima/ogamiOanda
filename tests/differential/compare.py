from __future__ import annotations

import json
import hashlib
from collections import Counter
from collections.abc import Collection, Sequence
from dataclasses import dataclass
from datetime import date
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
    mismatches: tuple[DiffMismatch, ...] = ()
    allowlist_applied_entries: tuple[AllowlistEntry, ...] = ()


class CompareError(ValueError):
    pass


MISSING_VALUE = {"$missing": True}


def compare_traces(
    *,
    scenario_id: str,
    baseline_trace: dict[str, Any],
    current_trace: dict[str, Any],
    allowlist_entries: list[AllowlistEntry],
) -> CompareResult:
    baseline = normalize_trace(baseline_trace)
    current = normalize_trace(current_trace)

    mismatches = tuple(_all_mismatches(baseline, current, pointer=""))
    scenario_entries = [
        entry for entry in allowlist_entries if entry.scenario_id == scenario_id
    ]
    applied: list[AllowlistEntry] = []
    unexpected: list[DiffMismatch] = []
    for mismatch in mismatches:
        matched_entry = _match_allowlist_entry(
            scenario_id,
            mismatch,
            scenario_entries,
            baseline,
            current,
        )
        if matched_entry is None:
            unexpected.append(mismatch)
        elif matched_entry not in applied:
            applied.append(matched_entry)

    stale = tuple(entry for entry in scenario_entries if entry not in applied)
    first_mismatch = unexpected[0] if unexpected else (mismatches[0] if mismatches else None)
    return CompareResult(
        matched=not unexpected and not stale,
        mismatch=first_mismatch,
        allowlist_applied=applied[0] if applied else None,
        stale_entries=stale,
        mismatches=tuple(unexpected),
        allowlist_applied_entries=tuple(applied),
    )


def load_allowlist(
    path: Path | None = None,
    *,
    as_of: date | None = None,
) -> list[AllowlistEntry]:
    file_path = path or ALLOWLIST_PATH
    if not file_path.exists():
        return []
    raw = json.loads(file_path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise CompareError("Allowlist must be a list")

    result = []
    delta_ids: set[str] = set()
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
        unknown = sorted(set(item) - required)
        if unknown:
            raise CompareError(f"Allowlist entry {index} unknown keys: {unknown}")
        if not item["scenario_id"]:
            raise CompareError(f"Allowlist entry {index}: scenario_id must be non-empty")
        pointer = str(item["pointer"])
        if not pointer.startswith("/"):
            raise CompareError(f"Allowlist entry {index}: pointer must be an absolute JSON pointer")
        if "*" in pointer:
            raise CompareError(f"Allowlist entry {index}: wildcard pointer is not allowed")
        for side in ("left", "right"):
            value = item[side]
            if isinstance(value, list):
                raise CompareError(
                    f"Allowlist entry {index}: {side} may not allowlist a list container"
                )
            if isinstance(value, dict) and set(value) not in (
                {"$missing"},
                {"$sha256"},
            ):
                raise CompareError(
                    f"Allowlist entry {index}: {side} may only use $missing or $sha256 matcher objects"
                )
        delta_id = str(item["delta_id"])
        if not delta_id or delta_id in delta_ids:
            raise CompareError(f"Allowlist entry {index}: delta_id must be unique and non-empty")
        delta_ids.add(delta_id)
        if not str(item["reason"]).strip() or not str(item["reference"]).strip():
            raise CompareError(f"Allowlist entry {index}: reason and reference must be non-empty")
        try:
            expires_on = date.fromisoformat(str(item["expires_on"]))
        except ValueError as error:
            raise CompareError(
                f"Allowlist entry {index}: expires_on must be ISO date"
            ) from error
        if expires_on < (as_of or date.today()):
            raise CompareError(f"Allowlist entry {index}: expired on {expires_on.isoformat()}")
        result.append(
            AllowlistEntry(
                delta_id=delta_id,
                scenario_id=str(item["scenario_id"]),
                pointer=pointer,
                left=item["left"],
                right=item["right"],
                reason=str(item["reason"]),
                reference=str(item["reference"]),
                expires_on=str(item["expires_on"]),
            )
        )
    return result


def verify_allowlist_application(
    *,
    allowlist_entries: Sequence[AllowlistEntry],
    applied_entries: Sequence[AllowlistEntry],
    scenario_ids: Collection[str],
    known_scenario_ids: Collection[str] | None = None,
) -> None:
    known_ids = set(known_scenario_ids or scenario_ids)
    orphan_entries = sorted(
        entry.delta_id
        for entry in allowlist_entries
        if entry.scenario_id not in known_ids
    )
    expected_ids = {
        entry.delta_id
        for entry in allowlist_entries
        if entry.scenario_id in scenario_ids
    }
    counts = Counter(entry.delta_id for entry in applied_entries)
    missing = sorted(expected_ids - set(counts))
    repeated = sorted(
        delta_id
        for delta_id, count in counts.items()
        if delta_id in expected_ids and count != 1
    )
    unexpected = sorted(set(counts) - expected_ids)
    if orphan_entries or missing or repeated or unexpected:
        raise CompareError(
            "Allowlist application mismatch: "
            f"orphan={orphan_entries}, missing={missing}, "
            f"repeated={repeated}, unexpected={unexpected}"
        )


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
        "unexpected_mismatches": [
            {
                "pointer": mismatch.pointer,
                "left": mismatch.left,
                "right": mismatch.right,
                "message": mismatch.message,
                "event_context": _event_context(
                    baseline_trace,
                    current_trace,
                    mismatch.pointer,
                ),
            }
            for mismatch in compare_result.mismatches
        ],
        "legacy_sha256": canonical_sha256(normalize_trace(baseline_trace)),
        "current_sha256": canonical_sha256(normalize_trace(current_trace)),
    }
    write_trace_atomic(output_dir / "diff.json", diff_payload)

    if legacy_log is not None:
        (output_dir / "legacy.log.txt").write_text(legacy_log, encoding="utf-8")

    return output_dir


def _all_mismatches(left: Any, right: Any, *, pointer: str):
    if type(left) is not type(right):
        yield DiffMismatch(pointer or "/", left, right, f"type mismatch: {type(left).__name__} != {type(right).__name__}")
        return

    if isinstance(left, dict):
        common_keys = sorted(set(left) & set(right))
        for key in common_keys:
            next_pointer = f"{pointer}/{_escape_pointer_segment(str(key))}" if pointer else f"/{_escape_pointer_segment(str(key))}"
            yield from _all_mismatches(left[key], right[key], pointer=next_pointer)
        for key in sorted(set(left) - set(right)):
            next_pointer = f"{pointer}/{_escape_pointer_segment(str(key))}" if pointer else f"/{_escape_pointer_segment(str(key))}"
            yield DiffMismatch(
                next_pointer,
                left[key],
                MISSING_VALUE,
                "mapping key missing on right",
            )
        for key in sorted(set(right) - set(left)):
            next_pointer = f"{pointer}/{_escape_pointer_segment(str(key))}" if pointer else f"/{_escape_pointer_segment(str(key))}"
            yield DiffMismatch(
                next_pointer,
                MISSING_VALUE,
                right[key],
                "mapping key missing on left",
            )
        return

    if isinstance(left, list):
        for index, (left_item, right_item) in enumerate(zip(left, right)):
            next_pointer = f"{pointer}/{index}" if pointer else f"/{index}"
            yield from _all_mismatches(left_item, right_item, pointer=next_pointer)
        for index in range(len(right), len(left)):
            next_pointer = f"{pointer}/{index}" if pointer else f"/{index}"
            yield DiffMismatch(
                next_pointer,
                left[index],
                MISSING_VALUE,
                "list element missing on right",
            )
        for index in range(len(left), len(right)):
            next_pointer = f"{pointer}/{index}" if pointer else f"/{index}"
            yield DiffMismatch(
                next_pointer,
                MISSING_VALUE,
                right[index],
                "list element missing on left",
            )
        return

    if left != right:
        yield DiffMismatch(pointer or "/", left, right, "scalar value differs")


def _match_allowlist_entry(
    scenario_id: str,
    mismatch: DiffMismatch,
    entries: list[AllowlistEntry],
    baseline: dict[str, Any],
    current: dict[str, Any],
) -> AllowlistEntry | None:
    for entry in entries:
        if entry.scenario_id != scenario_id:
            continue
        if entry.pointer == mismatch.pointer:
            if not _expected_value_matches(entry.left, mismatch.left):
                continue
            if not _expected_value_matches(entry.right, mismatch.right):
                continue
            return entry
        if not mismatch.pointer.startswith(entry.pointer.rstrip("/") + "/"):
            continue
        if not (_is_sha256_matcher(entry.left) and _is_sha256_matcher(entry.right)):
            continue
        baseline_value = _resolve_pointer(baseline, entry.pointer)
        current_value = _resolve_pointer(current, entry.pointer)
        if not _expected_value_matches(entry.left, baseline_value):
            continue
        if not _expected_value_matches(entry.right, current_value):
            continue
        return entry
    return None


def _expected_value_matches(expected: Any, actual: Any) -> bool:
    if _is_sha256_matcher(expected):
        digest = hashlib.sha256(canonical_json_bytes(actual)).hexdigest()
        return digest == str(expected["$sha256"])
    return expected == actual


def _is_sha256_matcher(value: Any) -> bool:
    return isinstance(value, dict) and set(value) == {"$sha256"}


def _resolve_pointer(document: Any, pointer: str) -> Any:
    if pointer == "":
        return document
    current = document
    for raw_segment in pointer.lstrip("/").split("/"):
        segment = raw_segment.replace("~1", "/").replace("~0", "~")
        if isinstance(current, dict):
            if segment not in current:
                return MISSING_VALUE
            current = current[segment]
        elif isinstance(current, list):
            try:
                index = int(segment)
            except ValueError:
                return MISSING_VALUE
            if not 0 <= index < len(current):
                return MISSING_VALUE
            current = current[index]
        else:
            return MISSING_VALUE
    return current


def _escape_pointer_segment(value: str) -> str:
    return value.replace("~", "~0").replace("/", "~1")


def _event_context(
    baseline_trace: dict[str, Any],
    current_trace: dict[str, Any],
    pointer: str,
) -> dict[str, Any] | None:
    segments = pointer.split("/")
    if len(segments) < 3 or segments[1] != "events":
        return None
    try:
        index = int(segments[2])
    except ValueError:
        return None

    def _window(trace: dict[str, Any]) -> list[Any]:
        events = trace.get("events", [])
        if not isinstance(events, list):
            return []
        start = max(0, index - 1)
        end = min(len(events), index + 2)
        return events[start:end]

    return {
        "event_index": index,
        "legacy": _window(baseline_trace),
        "current": _window(current_trace),
    }


def traces_byte_equal(left: dict[str, Any], right: dict[str, Any]) -> bool:
    return canonical_json_bytes(normalize_trace(left)) == canonical_json_bytes(normalize_trace(right))
