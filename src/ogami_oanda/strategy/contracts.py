"""Broker-agnostic contracts implemented by trusted strategy plugins."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Mapping, Protocol, TypeAlias, runtime_checkable

from ogami_oanda.domain.orders.models import OrderIntent
from ogami_oanda.domain.positions.models import PositionCommand, PositionSnapshot

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


@dataclass(frozen=True)
class StrategyDecision:
    """Commands and order intents requested by a strategy evaluation."""

    commands: tuple[PositionCommand, ...] = ()
    intents: tuple[OrderIntent, ...] = ()
    diagnostics: Mapping[str, JSONValue] = field(default_factory=dict)


@runtime_checkable
class TradingStrategy(Protocol):
    """Versioned plugin surface consumed by application services."""

    def decide(self, input: StrategyInput) -> StrategyDecision: ...

    def dump_state(self) -> JSONState: ...

    def load_state(self, state: Mapping[str, JSONValue]) -> None: ...
