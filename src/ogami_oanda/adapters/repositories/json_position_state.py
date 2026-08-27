from __future__ import annotations

import json
import math
import os
import shutil
from dataclasses import asdict, fields
from datetime import datetime
from pathlib import Path
from typing import Mapping

from ogami_oanda.application.ports.position_state import (
    BUILTIN_LINE_STRATEGY_ID,
    CheckpointLoadResult,
    CheckpointLoadStatus,
    PendingBrokerMutation,
    PortfolioAnalyticsState,
    PositionStateCheckpoint,
)
from ogami_oanda.domain.orders.models import (
    BrokerOrderRequest,
    Direction,
    OrderContext,
    OrderIntent,
    OrderPlan,
    OrderType,
)
from ogami_oanda.domain.positions.managed_position import ManagedPosition
from ogami_oanda.domain.positions.models import (
    OrderState,
    PositionRuntimeState,
    PositionSnapshot,
    SubmissionPhase,
    TradeState,
)


SCHEMA_VERSION = 2
_TOP_LEVEL_KEYS_V1 = frozenset(
    {
        "version",
        "account_hash",
        "pair",
        "slots",
        "transaction_cursor",
        "pending_mutations",
        "emitted_event_ids",
        "reported_event_ids",
        "analytics",
    }
)
_TOP_LEVEL_KEYS_V2 = _TOP_LEVEL_KEYS_V1 | frozenset(
    {
        "strategy_id",
        "strategy_state",
    }
)


class PositionStateWriteError(RuntimeError):
    pass


class _CheckpointDecodeError(ValueError):
    pass


class _SchemaMismatch(_CheckpointDecodeError):
    pass


class JsonPositionStateRepository:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.backup_path = self.path.with_suffix(self.path.suffix + ".bak")
        self._replace = os.replace

    def save(self, checkpoint: PositionStateCheckpoint) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        primary_temp = self.path.with_suffix(self.path.suffix + ".tmp")
        backup_temp = self.backup_path.with_suffix(self.backup_path.suffix + ".tmp")
        try:
            primary_is_valid = (
                self._load_path(
                    self.path,
                    checkpoint.account_hash,
                    checkpoint.pair,
                ).status
                is CheckpointLoadStatus.LOADED
            )
            if primary_is_valid:
                shutil.copyfile(self.path, backup_temp)
                self._fsync_file(backup_temp)
                self._replace(backup_temp, self.backup_path)
            payload = _encode_checkpoint(checkpoint)
            with primary_temp.open("w", encoding="utf-8") as state_file:
                json.dump(
                    payload,
                    state_file,
                    ensure_ascii=True,
                    allow_nan=False,
                    separators=(",", ":"),
                    sort_keys=True,
                )
                state_file.flush()
                os.fsync(state_file.fileno())
            self._replace(primary_temp, self.path)
            self._fsync_directory()
        except (OSError, TypeError, ValueError) as error:
            raise PositionStateWriteError(str(error)) from error
        finally:
            primary_temp.unlink(missing_ok=True)
            backup_temp.unlink(missing_ok=True)

    def load(
        self,
        *,
        expected_account_hash: str,
        expected_pair: str,
    ) -> CheckpointLoadResult:
        if not self.path.exists() and not self.backup_path.exists():
            return CheckpointLoadResult(CheckpointLoadStatus.MISSING)

        primary_result = self._load_path(
            self.path,
            expected_account_hash,
            expected_pair,
        )
        if primary_result.status in {
            CheckpointLoadStatus.LOADED,
            CheckpointLoadStatus.ACCOUNT_MISMATCH,
            CheckpointLoadStatus.PAIR_MISMATCH,
        }:
            return primary_result

        backup_result = self._load_path(
            self.backup_path,
            expected_account_hash,
            expected_pair,
        )
        if backup_result.status is CheckpointLoadStatus.LOADED:
            return CheckpointLoadResult(
                CheckpointLoadStatus.LOADED_FROM_BACKUP,
                backup_result.checkpoint,
                primary_result.reason,
            )
        if primary_result.status is CheckpointLoadStatus.SCHEMA_MISMATCH:
            return primary_result
        return CheckpointLoadResult(
            CheckpointLoadStatus.QUARANTINED,
            reason=primary_result.reason or backup_result.reason,
        )

    def _load_path(
        self,
        path: Path,
        expected_account_hash: str,
        expected_pair: str,
    ) -> CheckpointLoadResult:
        if not path.exists():
            return CheckpointLoadResult(CheckpointLoadStatus.MISSING)
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            checkpoint = _decode_checkpoint(raw)
        except _SchemaMismatch as error:
            return CheckpointLoadResult(
                CheckpointLoadStatus.SCHEMA_MISMATCH,
                reason=str(error),
            )
        except (json.JSONDecodeError, KeyError, OSError, TypeError, ValueError) as error:
            return CheckpointLoadResult(
                CheckpointLoadStatus.QUARANTINED,
                reason=str(error),
            )
        if checkpoint.account_hash != expected_account_hash:
            return CheckpointLoadResult(
                CheckpointLoadStatus.ACCOUNT_MISMATCH,
                reason="checkpoint account does not match configured account",
            )
        if checkpoint.pair != expected_pair:
            return CheckpointLoadResult(
                CheckpointLoadStatus.PAIR_MISMATCH,
                reason="checkpoint pair does not match configured pair",
            )
        return CheckpointLoadResult(CheckpointLoadStatus.LOADED, checkpoint)

    def _fsync_file(self, path: Path) -> None:
        with path.open("rb") as state_file:
            os.fsync(state_file.fileno())

    def _fsync_directory(self) -> None:
        descriptor = os.open(self.path.parent, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


def _encode_checkpoint(checkpoint: PositionStateCheckpoint) -> dict[str, object]:
    return {
        "version": SCHEMA_VERSION,
        "account_hash": checkpoint.account_hash,
        "pair": checkpoint.pair,
        "slots": [
            _encode_position(position) if position is not None else None
            for position in checkpoint.slots
        ],
        "transaction_cursor": checkpoint.transaction_cursor,
        "pending_mutations": [
            {
                **asdict(item),
                "prepared_at": _encode_datetime(item.prepared_at),
            }
            for item in checkpoint.pending_mutations
        ],
        "emitted_event_ids": sorted(checkpoint.emitted_event_ids),
        "reported_event_ids": sorted(checkpoint.reported_event_ids),
        "analytics": _encode_analytics(checkpoint.analytics),
        "strategy_id": checkpoint.strategy_id,
        "strategy_state": checkpoint.strategy_state,
    }


def _decode_checkpoint(raw: object) -> PositionStateCheckpoint:
    if not isinstance(raw, Mapping):
        raise _CheckpointDecodeError("checkpoint root must be an object")
    version = raw.get("version")
    if version not in {1, SCHEMA_VERSION}:
        raise _SchemaMismatch(f"unsupported checkpoint schema: {version}")
    allowed_keys = _TOP_LEVEL_KEYS_V1 if version == 1 else _TOP_LEVEL_KEYS_V2
    unknown = set(raw) - allowed_keys
    if unknown:
        raise _CheckpointDecodeError(
            f"unknown checkpoint fields: {', '.join(sorted(unknown))}"
        )
    if version == SCHEMA_VERSION and (
        "strategy_id" not in raw or "strategy_state" not in raw
    ):
        raise _CheckpointDecodeError(
            "schema v2 requires strategy_id and strategy_state"
        )
    slots = raw.get("slots")
    if not isinstance(slots, list):
        raise _CheckpointDecodeError("checkpoint slots must be a list")
    pending = raw.get("pending_mutations", [])
    if not isinstance(pending, list):
        raise _CheckpointDecodeError("pending_mutations must be a list")
    return PositionStateCheckpoint(
        account_hash=str(raw["account_hash"]),
        pair=str(raw["pair"]),
        slots=tuple(
            _decode_position(item) if item is not None else None
            for item in slots
        ),
        transaction_cursor=(
            str(raw["transaction_cursor"])
            if raw.get("transaction_cursor") is not None
            else None
        ),
        pending_mutations=tuple(
            PendingBrokerMutation(
                action=str(item["action"]),
                position_name=str(item["position_name"]),
                client_reference=str(item.get("client_reference", "")),
                broker_reference_id=(
                    str(item["broker_reference_id"])
                    if item.get("broker_reference_id") is not None
                    else None
                ),
                reason=str(item.get("reason", "")),
                stop_loss_price=_optional_float(item.get("stop_loss_price")),
                applied_lc_change_index=_optional_int(
                    item.get("applied_lc_change_index")
                ),
                candle_stop_loss_done=(
                    bool(item["candle_stop_loss_done"])
                    if item.get("candle_stop_loss_done") is not None
                    else None
                ),
                prepared_at=_decode_datetime(item.get("prepared_at")),
            )
            for item in pending
            if isinstance(item, Mapping)
        ),
        emitted_event_ids=frozenset(str(item) for item in raw.get("emitted_event_ids", [])),
        reported_event_ids=frozenset(str(item) for item in raw.get("reported_event_ids", [])),
        analytics=_decode_analytics(raw.get("analytics", {})),
        strategy_id=(
            BUILTIN_LINE_STRATEGY_ID
            if version == 1
            else raw["strategy_id"]
        ),
        strategy_state=(
            {}
            if version == 1
            else raw["strategy_state"]
        ),
    )


def _encode_position(position: ManagedPosition) -> dict[str, object]:
    return {
        "snapshot": {
            **asdict(position.snapshot),
            "order_state": position.snapshot.order_state.value,
            "trade_state": position.snapshot.trade_state.value,
        },
        "runtime": {
            "order_plan": _encode_order_plan(position.runtime.order_plan),
            "direction": position.runtime.direction,
            "target_price": position.runtime.target_price,
            "source": position.runtime.source,
            "line_strategy": position.runtime.line_strategy,
            "registered_at": _encode_datetime(position.runtime.registered_at),
            "filled_at": _encode_datetime(position.runtime.filled_at),
            "current_stop_loss": position.runtime.current_stop_loss,
            "applied_lc_change_index": position.runtime.applied_lc_change_index,
            "candle_stop_loss_done": position.runtime.candle_stop_loss_done,
            "linkage_id": position.runtime.linkage_id,
            "linkage_done": position.runtime.linkage_done,
            "close_requested": position.runtime.close_requested,
            "unrealized_pl": position.runtime.unrealized_pl,
            "realized_pl": position.runtime.realized_pl,
            "max_unrealized_pl": position.runtime.max_unrealized_pl,
            "min_unrealized_pl": position.runtime.min_unrealized_pl,
            "restored": position.runtime.restored,
            "watch_step1_started_at": _encode_datetime(position.runtime.watch_step1_started_at),
            "watch_step2_started_at": _encode_datetime(position.runtime.watch_step2_started_at),
            "watch_step1_over_price": position.runtime.watch_step1_over_price,
            "submission_reason": position.runtime.submission_reason,
            "submission_phase": position.runtime.submission_phase.value,
        },
    }


def _decode_position(raw: object) -> ManagedPosition:
    if not isinstance(raw, Mapping):
        raise _CheckpointDecodeError("position must be an object")
    snapshot_raw = raw.get("snapshot")
    runtime_raw = raw.get("runtime")
    if not isinstance(snapshot_raw, Mapping) or not isinstance(runtime_raw, Mapping):
        raise _CheckpointDecodeError("position snapshot/runtime must be objects")
    snapshot = PositionSnapshot(
        name=str(snapshot_raw["name"]),
        pair=str(snapshot_raw["pair"]),
        order_state=OrderState(str(snapshot_raw["order_state"])),
        trade_state=TradeState(str(snapshot_raw["trade_state"])),
        order_id=_optional_string(snapshot_raw.get("order_id")),
        trade_id=_optional_string(snapshot_raw.get("trade_id")),
        life=bool(snapshot_raw.get("life", False)),
        waiting_order=bool(snapshot_raw.get("waiting_order", False)),
        direction=_optional_int(snapshot_raw.get("direction")),
        target_price=_optional_float(snapshot_raw.get("target_price")),
        units=int(snapshot_raw.get("units", 0)),
        source=_optional_string(snapshot_raw.get("source")),
        line_strategy=_optional_string(snapshot_raw.get("line_strategy")),
        current_stop_loss=_optional_float(snapshot_raw.get("current_stop_loss")),
        current_price=_optional_float(snapshot_raw.get("current_price")),
        unrealized_pl=float(snapshot_raw.get("unrealized_pl", 0)),
        realized_pl=float(snapshot_raw.get("realized_pl", 0)),
        open_time=_optional_string(snapshot_raw.get("open_time")),
        close_time=_optional_string(snapshot_raw.get("close_time")),
        elapsed_seconds=float(snapshot_raw.get("elapsed_seconds", 0)),
        average_close_price=_optional_float(snapshot_raw.get("average_close_price")),
        client_reference=str(snapshot_raw.get("client_reference", "")),
    )
    runtime = PositionRuntimeState(
        order_plan=_decode_order_plan(runtime_raw.get("order_plan")),
        direction=int(runtime_raw.get("direction", 0)),
        target_price=float(runtime_raw.get("target_price", 0)),
        source=_optional_string(runtime_raw.get("source")),
        line_strategy=_optional_string(runtime_raw.get("line_strategy")),
        registered_at=_decode_datetime(runtime_raw.get("registered_at")),
        filled_at=_decode_datetime(runtime_raw.get("filled_at")),
        current_stop_loss=_optional_float(runtime_raw.get("current_stop_loss")),
        applied_lc_change_index=int(runtime_raw.get("applied_lc_change_index", -1)),
        candle_stop_loss_done=bool(runtime_raw.get("candle_stop_loss_done", False)),
        linkage_id=_optional_string(runtime_raw.get("linkage_id")),
        linkage_done=bool(runtime_raw.get("linkage_done", False)),
        close_requested=bool(runtime_raw.get("close_requested", False)),
        unrealized_pl=float(runtime_raw.get("unrealized_pl", 0)),
        realized_pl=float(runtime_raw.get("realized_pl", 0)),
        max_unrealized_pl=float(runtime_raw.get("max_unrealized_pl", 0)),
        min_unrealized_pl=float(runtime_raw.get("min_unrealized_pl", 0)),
        restored=bool(runtime_raw.get("restored", False)),
        watch_step1_started_at=_decode_datetime(runtime_raw.get("watch_step1_started_at")),
        watch_step2_started_at=_decode_datetime(runtime_raw.get("watch_step2_started_at")),
        watch_step1_over_price=float(runtime_raw.get("watch_step1_over_price", 0)),
        submission_reason=str(runtime_raw.get("submission_reason", "")),
        submission_phase=SubmissionPhase(
            str(runtime_raw.get("submission_phase", SubmissionPhase.NONE.value))
        ),
    )
    return ManagedPosition(snapshot, runtime)


def _encode_order_plan(plan: OrderPlan | None) -> dict[str, object] | None:
    if plan is None:
        return None
    intent = plan.intent
    request = plan.broker_request
    return {
        "intent": {
            "pair": intent.pair,
            "direction": intent.direction.value,
            "order_type": intent.order_type.value,
            "target": intent.target,
            "target_is_price": intent.target_is_price,
            "take_profit": intent.take_profit,
            "take_profit_is_price": intent.take_profit_is_price,
            "stop_loss": intent.stop_loss,
            "stop_loss_is_price": intent.stop_loss_is_price,
            "units": intent.units,
            "name": intent.name,
            "priority": intent.priority,
            "order_timeout_min": intent.order_timeout_min,
            "trade_timeout_min": intent.trade_timeout_min,
            "lc_change": [_plain_json_value(dict(item)) for item in intent.lc_change],
            "metadata": _plain_json_value(dict(intent.metadata)),
        },
        "context": asdict(plan.context),
        "target_price": plan.target_price,
        "take_profit_price": plan.take_profit_price,
        "stop_loss_price": plan.stop_loss_price,
        "take_profit_range": plan.take_profit_range,
        "stop_loss_range": plan.stop_loss_range,
        "broker_request": {
            **asdict(request),
            "order_type": request.order_type.value,
        },
    }


def _decode_order_plan(raw: object) -> OrderPlan | None:
    if raw is None:
        return None
    if not isinstance(raw, Mapping):
        raise _CheckpointDecodeError("order_plan must be an object")
    intent_raw = raw["intent"]
    context_raw = raw["context"]
    request_raw = raw["broker_request"]
    if not all(isinstance(item, Mapping) for item in (intent_raw, context_raw, request_raw)):
        raise _CheckpointDecodeError("order_plan members must be objects")
    metadata_value = _restore_json_value(dict(intent_raw.get("metadata", {})))
    if not isinstance(metadata_value, dict):
        raise _CheckpointDecodeError("intent metadata must be an object")
    metadata = metadata_value
    for key in ("linkage_order_names", "legacy_linkage_ids"):
        if isinstance(metadata.get(key), list):
            metadata[key] = tuple(metadata[key])
    intent = OrderIntent(
        pair=str(intent_raw["pair"]),
        direction=Direction(int(intent_raw["direction"])),
        order_type=OrderType(str(intent_raw["order_type"])),
        target=float(intent_raw["target"]),
        target_is_price=bool(intent_raw["target_is_price"]),
        take_profit=float(intent_raw["take_profit"]),
        take_profit_is_price=bool(intent_raw["take_profit_is_price"]),
        stop_loss=float(intent_raw["stop_loss"]),
        stop_loss_is_price=bool(intent_raw["stop_loss_is_price"]),
        units=int(intent_raw["units"]),
        name=str(intent_raw["name"]),
        priority=int(intent_raw["priority"]),
        order_timeout_min=int(intent_raw["order_timeout_min"]),
        trade_timeout_min=int(intent_raw.get("trade_timeout_min", 240)),
        lc_change=tuple(
            dict(_restore_json_value(item))
            for item in intent_raw.get("lc_change", [])
        ),
        metadata=metadata,
    )
    context = OrderContext(
        current_price=float(context_raw["current_price"]),
        decision_time=str(context_raw["decision_time"]),
        move_average=float(context_raw.get("move_average", 0)),
        account_mode=int(context_raw.get("account_mode", 2)),
    )
    request = BrokerOrderRequest(
        instrument=str(request_raw["instrument"]),
        units=int(request_raw["units"]),
        order_type=OrderType(str(request_raw["order_type"])),
        price=float(request_raw["price"]),
        take_profit_price=float(request_raw["take_profit_price"]),
        stop_loss_price=float(request_raw["stop_loss_price"]),
        client_reference=str(request_raw.get("client_reference", "")),
    )
    return OrderPlan(
        intent=intent,
        context=context,
        target_price=float(raw["target_price"]),
        take_profit_price=float(raw["take_profit_price"]),
        stop_loss_price=float(raw["stop_loss_price"]),
        take_profit_range=float(raw["take_profit_range"]),
        stop_loss_range=float(raw["stop_loss_range"]),
        broker_request=request,
    )


def _encode_analytics(state: PortfolioAnalyticsState) -> dict[str, object]:
    result = asdict(state)
    for field_name in (
        "total_yen",
        "total_yen_max",
        "total_yen_min",
        "total_price_diff",
        "total_price_diff_max",
        "total_price_diff_min",
        "total_pips",
        "total_pips_max",
        "total_pips_min",
    ):
        result[field_name] = _encode_float(float(result[field_name]))
    return _plain_json_value(result)


def _decode_analytics(raw: object) -> PortfolioAnalyticsState:
    if not isinstance(raw, Mapping):
        raise _CheckpointDecodeError("analytics must be an object")
    restored = _restore_json_value(dict(raw))
    if not isinstance(restored, dict):
        raise _CheckpointDecodeError("analytics must decode to an object")
    values = restored
    for field_name in (
        "total_yen",
        "total_yen_max",
        "total_yen_min",
        "total_price_diff",
        "total_price_diff_max",
        "total_price_diff_min",
        "total_pips",
        "total_pips_max",
        "total_pips_min",
    ):
        values[field_name] = _decode_float(values.get(field_name, 0))
    for field_name in (
        "history_plus_minus",
        "history_names",
        "history_name_plus_minus",
        "result_dic_arr",
    ):
        values[field_name] = tuple(values.get(field_name, ()))
    allowed = {item.name for item in fields(PortfolioAnalyticsState)}
    return PortfolioAnalyticsState(
        **{key: value for key, value in values.items() if key in allowed}
    )


def _plain_json_value(value: object) -> object:
    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, float):
        return _encode_float(value)
    if isinstance(value, datetime):
        return {"__datetime__": value.isoformat()}
    if isinstance(value, Mapping):
        return {str(key): _plain_json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain_json_value(item) for item in value]
    raise TypeError(f"unsupported checkpoint value: {type(value).__name__}")


def _restore_json_value(value: object) -> object:
    if isinstance(value, dict):
        if set(value) == {"__datetime__"}:
            return datetime.fromisoformat(str(value["__datetime__"]))
        return {
            str(key): _restore_json_value(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_restore_json_value(item) for item in value]
    return value


def _encode_float(value: float) -> float | str:
    if math.isinf(value):
        return "Infinity" if value > 0 else "-Infinity"
    if math.isnan(value):
        raise ValueError("NaN is not supported in position checkpoints")
    return value


def _decode_float(value: object) -> float:
    if value == "Infinity":
        return float("inf")
    if value == "-Infinity":
        return float("-inf")
    return float(value)


def _encode_datetime(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _decode_datetime(value: object) -> datetime | None:
    return datetime.fromisoformat(str(value)) if value is not None else None


def _optional_string(value: object) -> str | None:
    return str(value) if value is not None else None


def _optional_float(value: object) -> float | None:
    return float(value) if value is not None else None


def _optional_int(value: object) -> int | None:
    return int(value) if value is not None else None
