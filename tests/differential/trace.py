from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .constants import TRACE_SCHEMA_VERSION


@dataclass(frozen=True)
class TraceDocument:
    scenario_id: str
    runner: str
    trace: dict[str, Any]


class TraceSerializationError(ValueError):
    pass


def ensure_trace_envelope(trace: dict[str, Any], *, scenario_id: str, runner: str) -> dict[str, Any]:
    if not isinstance(trace, dict):
        raise TraceSerializationError("trace must be object")
    base = {
        "schema_version": TRACE_SCHEMA_VERSION,
        "scenario_id": scenario_id,
        "runner": runner,
    }
    merged = base | trace
    if "events" not in merged:
        merged["events"] = []
    if not isinstance(merged["events"], list):
        raise TraceSerializationError("trace.events must be list")
    return merged


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def write_trace_atomic(path: Path, trace: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(canonical_json_bytes(trace))
    tmp.replace(path)


def read_trace(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))
