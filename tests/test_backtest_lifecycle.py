import csv
from dataclasses import replace
from datetime import datetime, timedelta

import pytest

from ogami_oanda.domain.market.history import HistoricalCandle, OHLC
from ogami_oanda.domain.orders.models import Direction, OrderIntent, OrderType
from ogami_oanda.entrypoints.backtest_run import run_backtest
from ogami_oanda.strategy.shared.contracts import StrategyCommand, StrategyCommandAction, StrategyDecision
from tests.test_backtest_run import ExampleStrategy, START


def intent(name, source, **overrides):
    return replace(OrderIntent(
        "USD_JPY", Direction.BUY, OrderType.MARKET, 0, False,
        10, False, 10, False, 100, name, 1, 1,
        metadata={"source": source, "candle_lc_enabled": False},
    ), **overrides)


class ScriptedStrategy(ExampleStrategy):
    data_requirements = {}

    def __init__(self, decisions):
        super().__init__()
        self.decisions = decisions

    def decide(self, input):
        self.count += 1
        return self.decisions.get(self.count, StrategyDecision())


def replay(tmp_path, decisions, *, rising=False):
    def history():
        for index in range(24):
            value = 150 + index * .01 if rising else 150
            price = OHLC(value, value, value, value)
            yield HistoricalCandle(START + timedelta(seconds=index * 5), price, price, price)

    summary = run_backtest(ScriptedStrategy(decisions), "lifecycle", "USD_JPY", history(), START,
                           START + timedelta(minutes=2), initial_balance=10000, output_dir=tmp_path / "result")
    with (tmp_path / "result" / "orders.csv").open() as stream:
        return summary, list(csv.DictReader(stream))


def test_source_actions_preserve_other_source_exposure_and_pending_orders(tmp_path):
    decisions = {
        1: StrategyDecision(intents=(
            intent("alpha-open", "alpha"), intent("beta-open", "beta"),
            intent("alpha-pending", "alpha", order_type=OrderType.LIMIT, target=140, target_is_price=True),
            intent("beta-pending", "beta", order_type=OrderType.LIMIT, target=139, target_is_price=True),
        )),
        2: StrategyDecision(commands=(
            StrategyCommand(StrategyCommandAction.CANCEL_PENDING, "alpha", "cancel-alpha"),
            StrategyCommand(StrategyCommandAction.REDUCE_EXPOSURE, "alpha", "reduce-alpha", 40),
        )),
        3: StrategyDecision(commands=(StrategyCommand(StrategyCommandAction.CLOSE_ALL, "alpha", "close-alpha"),)),
    }
    summary, events = replay(tmp_path, decisions)
    reductions = [event for event in events if event["event"] == "REDUCE"]
    assert [(event["trade_id"], int(event["units"])) for event in reductions] == [("trade-1", 40)]
    closes = [event for event in events if event["event"] == "CLOSE"]
    assert [(event["trade_id"], int(event["units"]), event["reason"]) for event in closes] == [
        ("trade-1", 60, "MARKET_CLOSE"), ("trade-2", 100, "END_OF_TEST")]
    cancellations = [event for event in events if event["event"] == "CANCEL"]
    assert [event["order_id"] for event in cancellations] == ["order-3", "order-4"]
    assert cancellations[0]["time"] < cancellations[1]["time"]
    assert summary["trade_count"] == 2


def test_replay_clock_drives_order_and_position_expiry(tmp_path):
    summary, events = replay(tmp_path, {
        1: StrategyDecision(intents=(
            intent("expires", "alpha", trade_timeout_min=1,
                   metadata={"source": "alpha", "trade_timeout_enabled": True, "candle_lc_enabled": False}),
            intent("pending", "beta", order_type=OrderType.LIMIT, target=140, target_is_price=True),
        )),
    })
    assert summary["trade_count"] == 1
    assert [event["reason"] for event in events if event["event"] == "CLOSE"] == ["MARKET_CLOSE"]
    assert any(event["event"] == "CANCEL" and event["order_id"] == "order-2" for event in events)
    assert any(event["reason"] == "order_timeout" for event in events)
    assert any(event["reason"] == "trade_timeout" for event in events)


def test_staged_stop_loss_is_applied_through_shared_position_service(tmp_path):
    _, events = replay(tmp_path, {
        1: StrategyDecision(intents=(intent("staged", "alpha", lc_change=(
            {"exe": True, "trigger": .03, "ensure": .01, "time_after": 0},
            {"exe": True, "trigger": .08, "ensure": .05, "time_after": 0},
        )),)),
    }, rising=True)
    assert [float(event["price"]) for event in events if event["event"] == "AMEND"] == pytest.approx([150.02, 150.06])


def test_main_fill_cancels_only_its_linked_pending_order(tmp_path):
    _, events = replay(tmp_path, {
        1: StrategyDecision(intents=(
            intent("main", "main", metadata={"source": "main", "linkage_id": "group", "candle_lc_enabled": False}),
            intent("linked", "linked", direction=Direction.SELL, order_type=OrderType.LIMIT,
                   target=151, target_is_price=True,
                   metadata={"source": "linked", "linkage_id": "group", "candle_lc_enabled": False}),
        )),
    })
    cancellations = [event for event in events if event["event"] == "CANCEL"]
    assert [event["order_id"] for event in cancellations] == ["order-2"]
    assert datetime.fromisoformat(cancellations[0]["time"]) == START + timedelta(seconds=10)
