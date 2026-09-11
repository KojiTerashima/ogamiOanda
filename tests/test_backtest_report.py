import json
from datetime import datetime, timezone

import pytest

from ogami_oanda.adapters.backtest.report import BacktestReport
from tests.test_backtest_broker import bar, broker, request


def test_drawdown_tracks_s5_equity_peak_not_only_realized_balance(tmp_path):
    output = tmp_path / "report"
    report = BacktestReport(output, {}, 100)
    at = datetime(2024, 1, 2, tzinfo=timezone.utc)
    report.mark(at, 100, 25)
    report.mark(at, 105, -15)
    report.mark(at, 110, 0)
    assert report.max_drawdown == 35
    assert report.max_drawdown_pct == pytest.approx(28)
    report.finish({})
    assert json.loads((output / "run.json").read_text())["status"] == "complete"


def test_trade_statistics_net_partial_profits_and_losses_before_counting_wins():
    simulation = broker()
    simulation.submit(request(tp=160, sl=140))
    simulation.advance(bar(spread=0))
    simulation.close_trade("trade-1", 40)
    simulation.advance(bar(1, open=151, high=151, low=151, close=151, spread=0))
    simulation.close_trade("trade-1")
    simulation.advance(bar(2, open=149, high=149, low=149, close=149, spread=0))
    assert simulation.completed_trades == 1
    assert simulation.winning_trades == 0
    assert simulation.gross_profit == 0
    assert simulation.gross_loss == pytest.approx(20)
    assert simulation.balance == pytest.approx(9980)
    assert simulation.monthly == {"2024-01": -20}
