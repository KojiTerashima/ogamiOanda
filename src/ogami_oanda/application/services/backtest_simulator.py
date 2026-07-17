from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from ogami_oanda.domain.orders.models import Direction


class ExitReason(str, Enum):
    TAKE_PROFIT = "TAKE_PROFIT"
    STOP_LOSS = "STOP_LOSS"


@dataclass(frozen=True)
class PriceCandle:
    high: float
    low: float
    close: float


@dataclass(frozen=True)
class SimulatedExit:
    reason: ExitReason
    price: float


class BacktestSimulator:
    def evaluate_exit(
        self,
        direction: Direction,
        take_profit_price: float,
        stop_loss_price: float,
        candle: PriceCandle,
    ) -> SimulatedExit | None:
        if direction is Direction.BUY:
            take_profit_hit = candle.high >= take_profit_price
            stop_loss_hit = candle.low <= stop_loss_price
        else:
            take_profit_hit = candle.low <= take_profit_price
            stop_loss_hit = candle.high >= stop_loss_price
        if stop_loss_hit:
            return SimulatedExit(ExitReason.STOP_LOSS, stop_loss_price)
        if take_profit_hit:
            return SimulatedExit(ExitReason.TAKE_PROFIT, take_profit_price)
        return None
