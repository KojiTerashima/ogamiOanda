"""Broker-agnostic contracts implemented by trusted strategy plugins."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Mapping, Protocol, TypeAlias, runtime_checkable

from ogami_oanda.domain.orders.models import OrderIntent
from ogami_oanda.domain.positions.models import PositionSnapshot

JSONScalar: TypeAlias = str | int | float | bool | None
JSONValue: TypeAlias = JSONScalar | list["JSONValue"] | dict[str, "JSONValue"]
JSONState: TypeAlias = dict[str, JSONValue]


@dataclass(frozen=True)
class StrategyQuote:
    """A market quote supplied to a strategy without exposing a broker adapter."""

    pair: str
    bid: float
    ask: float
    mid: float
    tradeable: bool = True
    source_time: datetime | None = None


@dataclass(frozen=True)
class StrategyInput:
    """The broker-neutral data available for one strategy evaluation."""

    quote: StrategyQuote
    positions: tuple[PositionSnapshot, ...] = ()
    candles: object | None = None
    evaluation_time: datetime | None = None


class StrategyCommandAction(str, Enum):
    """Broker-neutral source-scoped portfolio actions."""

    CANCEL_PENDING = "CANCEL_PENDING"
    REDUCE_EXPOSURE = "REDUCE_EXPOSURE"
    CLOSE_ALL = "CLOSE_ALL"


@dataclass(frozen=True)
class StrategyCommand:
    """A portfolio action confined to positions owned by one strategy source."""

    action: StrategyCommandAction
    source: str
    reason: str
    units: int | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.action, StrategyCommandAction):
            raise ValueError("strategy command action must be a StrategyCommandAction")
        if not self.source:
            raise ValueError("strategy command source must not be empty")
        if self.action is StrategyCommandAction.REDUCE_EXPOSURE:
            if type(self.units) is not int or self.units <= 0:
                raise ValueError("REDUCE_EXPOSURE units must be a positive integer")
        elif self.units is not None:
            raise ValueError(f"units are only valid for {StrategyCommandAction.REDUCE_EXPOSURE.value}")


@dataclass(frozen=True)
class StrategyDecision:
    """Commands and order intents requested by a strategy evaluation."""

    commands: tuple[StrategyCommand, ...] = ()
    intents: tuple[OrderIntent, ...] = ()
    diagnostics: Mapping[str, JSONValue] = field(default_factory=dict)


@runtime_checkable
class TradingStrategy(Protocol):
    """Versioned plugin surface consumed by application services."""

    def decide(self, input: StrategyInput) -> StrategyDecision: ...

    def dump_state(self) -> JSONState: ...

    def load_state(self, state: Mapping[str, JSONValue]) -> None: ...
