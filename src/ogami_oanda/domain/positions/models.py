from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class OrderState(str, Enum):
    REGISTERED = "REGISTERED"
    WATCHING = "WATCHING"
    PENDING = "PENDING"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"
    ERROR = "ERROR"


class TradeState(str, Enum):
    NONE = "NONE"
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    ERROR = "ERROR"


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
