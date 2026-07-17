import pytest

from ogami_oanda.application.services.backtest_simulator import (
    BacktestSimulator,
    ExitReason,
    PriceCandle,
)
from ogami_oanda.domain.orders.models import Direction


@pytest.mark.contract
@pytest.mark.parametrize(
    ("direction", "candle", "expected_reason", "expected_price"),
    [
        (Direction.BUY, PriceCandle(high=150.25, low=150.05, close=150.20), ExitReason.TAKE_PROFIT, 150.20),
        (Direction.BUY, PriceCandle(high=150.15, low=149.85, close=149.90), ExitReason.STOP_LOSS, 149.90),
        (Direction.SELL, PriceCandle(high=150.10, low=149.75, close=149.80), ExitReason.TAKE_PROFIT, 149.80),
        (Direction.SELL, PriceCandle(high=150.25, low=149.95, close=150.20), ExitReason.STOP_LOSS, 150.20),
    ],
)
def test_simulator_evaluates_take_profit_and_stop_loss(direction, candle, expected_reason, expected_price):
    result = BacktestSimulator().evaluate_exit(direction, 150.20 if direction is Direction.BUY else 149.80, 149.90 if direction is Direction.BUY else 150.20, candle)

    assert result is not None
    assert result.reason is expected_reason
    assert result.price == expected_price


@pytest.mark.contract
def test_simulator_returns_none_without_exit_and_uses_stop_loss_for_ambiguous_candle():
    simulator = BacktestSimulator()

    assert simulator.evaluate_exit(Direction.BUY, 150.20, 149.90, PriceCandle(high=150.19, low=149.91, close=150.00)) is None
    result = simulator.evaluate_exit(Direction.BUY, 150.20, 149.90, PriceCandle(high=150.25, low=149.85, close=150.00))
    assert result is not None
    assert result.reason is ExitReason.STOP_LOSS
    assert result.price == 149.90
