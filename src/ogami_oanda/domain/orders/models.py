from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Mapping


class Direction(int, Enum):
    SELL = -1
    BUY = 1


class OrderType(str, Enum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    STOP = "STOP"


def _frozen_metadata(metadata: Mapping[str, object]) -> Mapping[str, object]:
    return MappingProxyType(dict(metadata))


@dataclass(frozen=True)
class OrderIntent:
    pair: str
    direction: Direction
    order_type: OrderType
    target: float
    target_is_price: bool
    take_profit: float
    take_profit_is_price: bool
    stop_loss: float
    stop_loss_is_price: bool
    units: int
    name: str
    priority: int
    order_timeout_min: int
    trade_timeout_min: int = 240
    lc_change: tuple[Mapping[str, object], ...] = ()
    metadata: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "lc_change", tuple(dict(item) for item in self.lc_change))
        object.__setattr__(self, "metadata", _frozen_metadata(self.metadata))


@dataclass(frozen=True)
class OrderContext:
    current_price: float
    decision_time: str
    move_average: float = 0.0
    account_mode: int = 2


@dataclass(frozen=True)
class BrokerOrderRequest:
    instrument: str
    units: int
    order_type: OrderType
    price: float
    take_profit_price: float
    stop_loss_price: float


@dataclass(frozen=True)
class OrderPlan:
    intent: OrderIntent
    context: OrderContext
    target_price: float
    take_profit_price: float
    stop_loss_price: float
    take_profit_range: float
    stop_loss_range: float
    broker_request: BrokerOrderRequest
