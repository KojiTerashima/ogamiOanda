from __future__ import annotations

import hashlib
from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Mapping, Protocol, runtime_checkable

from ogami_oanda.domain.orders.models import OrderIntent
from ogami_oanda.domain.positions.managed_position import ManagedPosition


class CheckpointLoadStatus(str, Enum):
    LOADED = "LOADED"
    LOADED_FROM_BACKUP = "LOADED_FROM_BACKUP"
    MISSING = "MISSING"
    ACCOUNT_MISMATCH = "ACCOUNT_MISMATCH"
    PAIR_MISMATCH = "PAIR_MISMATCH"
    SCHEMA_MISMATCH = "SCHEMA_MISMATCH"
    QUARANTINED = "QUARANTINED"


@dataclass(frozen=True)
class PendingBrokerMutation:
    action: str
    position_name: str
    client_reference: str = ""
    broker_reference_id: str | None = None
    reason: str = ""


@dataclass(frozen=True)
class PortfolioAnalyticsState:
    total_yen: float = 0.0
    total_yen_max: float = 0.0
    total_yen_min: float = float("inf")
    total_price_diff: float = 0.0
    total_price_diff_max: float = 0.0
    total_price_diff_min: float = float("inf")
    total_pips: float = 0.0
    total_pips_max: float = 0.0
    total_pips_min: float = float("inf")
    plus_yen_position_num: int = 0
    minus_yen_position_num: int = 0
    lc_change_num: int = 0
    before_latest_price_diff: float = 0.0
    before_latest_pl_pips: float = 0.0
    before_latest_plu: float = 0.0
    before_latest_name: str = ""
    history_plus_minus: tuple[float, ...] = (0.0,)
    history_names: tuple[str, ...] = ("0",)
    history_name_plus_minus: tuple[Mapping[str, object], ...] = ()
    result_dic_arr: tuple[Mapping[str, object], ...] = ()
    result_row: int = 7


@dataclass(frozen=True)
class PositionStateCheckpoint:
    account_hash: str
    pair: str
    slots: tuple[ManagedPosition | None, ...]
    transaction_cursor: str | None = None
    pending_mutations: tuple[PendingBrokerMutation, ...] = ()
    emitted_event_ids: frozenset[str] = frozenset()
    reported_event_ids: frozenset[str] = frozenset()
    analytics: PortfolioAnalyticsState = field(default_factory=PortfolioAnalyticsState)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "slots",
            tuple(_sanitized_position(position) for position in self.slots),
        )
        object.__setattr__(self, "pending_mutations", tuple(self.pending_mutations))
        object.__setattr__(self, "emitted_event_ids", frozenset(self.emitted_event_ids))
        object.__setattr__(self, "reported_event_ids", frozenset(self.reported_event_ids))


@dataclass(frozen=True)
class CheckpointLoadResult:
    status: CheckpointLoadStatus
    checkpoint: PositionStateCheckpoint | None = None
    reason: str = ""


@runtime_checkable
class PositionStateRepository(Protocol):
    def save(self, checkpoint: PositionStateCheckpoint) -> None: ...

    def load(
        self,
        *,
        expected_account_hash: str,
        expected_pair: str,
    ) -> CheckpointLoadResult: ...


def account_identity_hash(account_id: str) -> str:
    return hashlib.sha256(account_id.encode("utf-8")).hexdigest()[:24]


_PERSISTED_METADATA_KEYS = frozenset(
    {
        "source",
        "line_strategy",
        "linkage_id",
        "linkage_order_names",
        "legacy_linkage_ids",
        "trade_timeout_enabled",
        "candle_lc_enabled",
        "name_ymdhms",
        "memo",
        "lc_change_str",
        "lc_price_original",
        "lc_price_original_plan",
        "tp_price_original",
        "tp_price_original_plan",
        "move_ave60",
        "current_price_gap",
        "current_candle_price_gap",
        "target_distance_pips",
        "gap_target_price_pips",
        "max_plus_pips",
        "max_minus_pips",
        "max_plus",
        "max_minus",
        "order_permission",
        "watching_price",
        "candle_lc_change_type",
        "legacy_plan_metadata",
    }
)


def persisted_metadata(metadata: Mapping[str, object]) -> dict[str, object]:
    return {
        key: value
        for key, raw_value in metadata.items()
        if key in _PERSISTED_METADATA_KEYS
        and (value := _json_compatible_value(raw_value)) is not _UNSUPPORTED
    }


def _sanitized_position(position: ManagedPosition | None) -> ManagedPosition | None:
    if position is None or position.runtime.order_plan is None:
        return position
    plan = position.runtime.order_plan
    intent = plan.intent
    sanitized_intent = OrderIntent(
        pair=intent.pair,
        direction=intent.direction,
        order_type=intent.order_type,
        target=intent.target,
        target_is_price=intent.target_is_price,
        take_profit=intent.take_profit,
        take_profit_is_price=intent.take_profit_is_price,
        stop_loss=intent.stop_loss,
        stop_loss_is_price=intent.stop_loss_is_price,
        units=intent.units,
        name=intent.name,
        priority=intent.priority,
        order_timeout_min=intent.order_timeout_min,
        trade_timeout_min=intent.trade_timeout_min,
        lc_change=intent.lc_change,
        metadata=persisted_metadata(intent.metadata),
    )
    sanitized_plan = replace(plan, intent=sanitized_intent)
    return replace(
        position,
        runtime=replace(position.runtime, order_plan=sanitized_plan),
    )


class _Unsupported:
    pass


_UNSUPPORTED = _Unsupported()


def _json_compatible_value(value: object) -> object:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Mapping):
        result: dict[str, object] = {}
        for key, item in value.items():
            normalized = _json_compatible_value(item)
            if normalized is not _UNSUPPORTED:
                result[str(key)] = normalized
        return result
    if isinstance(value, (tuple, list)):
        result = []
        for item in value:
            normalized = _json_compatible_value(item)
            if normalized is not _UNSUPPORTED:
                result.append(normalized)
        return tuple(result) if isinstance(value, tuple) else result
    return _UNSUPPORTED
