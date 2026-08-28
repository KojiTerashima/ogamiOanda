from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Mapping

from ogami_oanda.domain.orders.models import OrderPlan


class OrderState(str, Enum):
    REGISTERED = "REGISTERED"
    WATCHING = "WATCHING"
    PENDING = "PENDING"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"
    SUBMISSION_UNCERTAIN = "SUBMISSION_UNCERTAIN"
    ERROR = "ERROR"


class TradeState(str, Enum):
    NONE = "NONE"
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    ERROR = "ERROR"


class SubmissionPhase(str, Enum):
    NONE = "NONE"
    PREPARED = "PREPARED"
    WATCHING = "WATCHING"
    SUBMITTING = "SUBMITTING"
    PENDING = "PENDING"
    FILLED = "FILLED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"
    UNKNOWN = "UNKNOWN"
    TERMINAL = "TERMINAL"


@dataclass(frozen=True)
class PositionSnapshot:
    name: str
    pair: str
    order_state: OrderState
    trade_state: TradeState
    order_id: str | None = None
    trade_id: str | None = None
    life: bool = False
    waiting_order: bool = False
    direction: int | None = None
    target_price: float | None = None
    units: int = 0
    source: str | None = None
    line_strategy: str | None = None
    current_stop_loss: float | None = None
    current_price: float | None = None
    unrealized_pl: float = 0.0
    realized_pl: float = 0.0
    open_time: str | None = None
    close_time: str | None = None
    elapsed_seconds: float = 0.0
    average_close_price: float | None = None
    client_reference: str = ""
    # Raw OANDA OrderFillReason for a closed trade.  This is deliberately
    # optional so snapshots from other broker implementations remain valid.
    close_reason: str = ""


@dataclass(frozen=True)
class PositionRuntimeState:
    order_plan: OrderPlan | None = None
    direction: int = 0
    target_price: float = 0.0
    source: str | None = None
    line_strategy: str | None = None
    registered_at: datetime | None = None
    filled_at: datetime | None = None
    current_stop_loss: float | None = None
    applied_lc_change_index: int = -1
    candle_stop_loss_done: bool = False
    linkage_id: str | None = None
    linkage_done: bool = False
    close_requested: bool = False
    unrealized_pl: float = 0.0
    realized_pl: float = 0.0
    max_unrealized_pl: float = 0.0
    min_unrealized_pl: float = 0.0
    restored: bool = False
    watch_step1_started_at: datetime | None = None
    watch_step2_started_at: datetime | None = None
    watch_step1_over_price: float = 0.0
    submission_reason: str = ""
    submission_phase: SubmissionPhase = SubmissionPhase.NONE


@dataclass(frozen=True)
class PositionCommand:
    action: str
    reference_id: str | None
    reason: str
    stop_loss_price: float | None = None
    data: Mapping[str, object] | None = None


@dataclass(frozen=True)
class PositionEvent:
    event_id: str
    kind: str
    name: str
    pair: str
    occurred_at: datetime
    data: Mapping[str, object]
