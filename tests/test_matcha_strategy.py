from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import yaml

from ogami_oanda.domain.orders.models import Direction, OrderType
from ogami_oanda.domain.positions.models import OrderState, PositionSnapshot, TradeState
from ogami_oanda.strategy.contracts import StrategyCommand, StrategyCommandAction, StrategyInput, StrategyQuote


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "matcha_bf_literals.json"
MATCHA_YAML = Path(__file__).parents[1] / "src" / "ogami_oanda" / "strategy" / "matcha_param2019_oanda.yaml"
NOW = datetime(2026, 8, 27, 12, 0, tzinfo=timezone.utc)


def _config(**overrides: object) -> dict[str, object]:
    config: dict[str, object] = {
        "pair": "USD_JPY",
        "LotSize": 1000,
        "MaxLotSize": 20000,
        "MaxPos": 1,
        "sfdCheck": True,
        "AutoLot": False,
        "Leverage": 1.7,
        "Cancel": False,
        "Cancel_len": 5,
        "siguma_1": 0.15,
        "siguma_2": 0.8,
        "siguma_3": 1.0,
        "siguma_4": 1.0,
        "pastPrice_len": 25,
        "std_len": 250,
        "dp": 0.0005,
        "CTP": 0,
        "BreakOut": True,
        "stop_latency": 1900,
        "max_latency": 1900,
        "tp_sl_amount_mode": True,
        "tp_sl_close_intent_suppress": True,
        "take_profit_amount": 20.0,
        "stop_loss_amount": 20.0,
        "take_profit_distance": 0.04,
        "stop_loss_distance": 0.04,
        "timescale": 60,
        "minutes_to_expire": 7,
        "close_position": False,
    }
    config.update(overrides)
    return config


def _newest_first_candles(oldest_first_closes: list[float]) -> list[dict[str, object]]:
    oldest = datetime(2026, 8, 27, 11, 0, tzinfo=timezone.utc)
    records = [
        {
            "time": (oldest + timedelta(minutes=index)).isoformat(),
            "open": close,
            "high": close,
            "low": close,
            "close": close,
        }
        for index, close in enumerate(oldest_first_closes)
    ]
    return list(reversed(records))


def _strategy_input(
    closes: list[float],
    *,
    mid: float,
    positions: tuple[PositionSnapshot, ...] = (),
    source_time: datetime | None = NOW,
    evaluation_time: datetime | None = NOW,
    tradeable: bool = True,
) -> StrategyInput:
    return StrategyInput(
        quote=StrategyQuote(
            "USD_JPY",
            mid - 0.01,
            mid + 0.01,
            mid,
            tradeable=tradeable,
            source_time=source_time,
        ),
        positions=positions,
        candles=_newest_first_candles(closes),
        evaluation_time=evaluation_time,
    )


def _position(direction: Direction, units: int) -> PositionSnapshot:
    return PositionSnapshot(
        name="matcha-position",
        pair="USD_JPY",
        order_state=OrderState.FILLED,
        trade_state=TradeState.OPEN,
        trade_id="trade-1",
        life=True,
        direction=direction.value,
        units=units,
        source="matcha_oanda",
    )


def _normal_input(*, positions: tuple[PositionSnapshot, ...] = ()) -> StrategyInput:
    return _strategy_input([10, 10, 99, 100, 101, 100, 100], mid=100, positions=positions)


def _breakout_input(signal: int, *, positions: tuple[PositionSnapshot, ...] = ()) -> StrategyInput:
    newest = 105 if signal == 1 else 95
    mid = 101 if signal == 1 else 99
    return _strategy_input([100, 100, 100, 100, 100, 100, newest], mid=mid, positions=positions)


def _normal_strategy(**overrides: object):
    from ogami_oanda.strategy.matcha_oanda import create_strategy

    return create_strategy(
        _config(
            std_len=4,
            pastPrice_len=2,
            dp=0,
            siguma_1=1,
            siguma_2=2,
            siguma_3=3,
            BreakOut=False,
            **overrides,
        )
    )


def _breakout_strategy(**overrides: object):
    from ogami_oanda.strategy.matcha_oanda import create_strategy

    return create_strategy(
        _config(
            std_len=3,
            pastPrice_len=2,
            dp=0,
            siguma_1=0,
            siguma_2=1,
            siguma_3=1,
            siguma_4=1,
            BreakOut=True,
            **overrides,
        )
    )


def test_strategy_contract_supplies_evaluation_time_and_typed_source_scoped_commands():
    strategy_input = StrategyInput(
        StrategyQuote("USD_JPY", 149.99, 150.01, 150.0),
        evaluation_time=NOW,
    )
    command = StrategyCommand(
        action=StrategyCommandAction.REDUCE_EXPOSURE,
        source="matcha_oanda",
        reason="maximum_exposure",
        units=1000,
    )

    assert strategy_input.evaluation_time == NOW
    assert command.action.value == "REDUCE_EXPOSURE"
    assert command.units == 1000
    with pytest.raises(ValueError, match="positive"):
        StrategyCommand(StrategyCommandAction.REDUCE_EXPOSURE, "matcha_oanda", "bad", 0)
    with pytest.raises(ValueError, match="only valid"):
        StrategyCommand(StrategyCommandAction.CLOSE_ALL, "matcha_oanda", "bad", 1)
    with pytest.raises(ValueError, match="action"):
        StrategyCommand("DELETE", "matcha_oanda", "bad")  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("key", "unsupported"),
    [
        ("pair", "EUR_USD"),
        ("AutoLot", True),
        ("Cancel", True),
        ("MaxPos", 2),
        ("tp_sl_amount_mode", False),
        ("tp_sl_close_intent_suppress", False),
        ("close_position", True),
        ("timescale", 5),
    ],
)
def test_factory_rejects_each_unsupported_initial_route(key: str, unsupported: object):
    from ogami_oanda.strategy.matcha_oanda import create_strategy

    with pytest.raises(ValueError, match=rf"{key}.*supported"):
        create_strategy(_config(**{key: unsupported}))


def test_factory_accepts_supported_tunable_values():
    from ogami_oanda.strategy.matcha_oanda import create_strategy

    strategy = create_strategy(
        _config(
            LotSize=1200,
            MaxLotSize=1800,
            Cancel_len=3,
            siguma_1=0.2,
            siguma_2=0.7,
            siguma_3=1.2,
            siguma_4=1.4,
            pastPrice_len=4,
            std_len=8,
            dp=0.001,
            CTP=3,
            BreakOut=False,
            stop_latency=800,
            max_latency=1200,
            take_profit_amount=30,
            stop_loss_amount=15,
        )
    )

    assert strategy.pair == "USD_JPY"
    assert strategy.config.lot_size == 1200
    assert strategy.config.siguma_4 == 1.4
    assert strategy.config.minutes_to_expire == 7


@pytest.mark.parametrize("unsupported", [9, 6, 7.0, True])
def test_factory_rejects_minutes_to_expire_outside_exact_v1_route(unsupported: object):
    from ogami_oanda.strategy.matcha_oanda import create_strategy

    with pytest.raises(ValueError, match="minutes_to_expire.*supported"):
        create_strategy(_config(minutes_to_expire=unsupported))


def test_factory_accepts_zero_past_window_to_disable_breakout_threshold():
    from ogami_oanda.strategy.matcha_oanda import create_strategy

    strategy = create_strategy(_config(pastPrice_len=0))

    assert strategy.config.past_price_len == 0


def test_destination_yaml_is_loadable_sanitized_and_retains_notification_todo_marker():
    text = MATCHA_YAML.read_text(encoding="utf-8")
    config = yaml.safe_load(text)

    assert isinstance(config, dict)
    assert config["pair"] == "USD_JPY"
    assert not any("notification" in str(key).lower() or "webhook" in str(key).lower() for key in config)
    assert text.count("# TODO(notification-integration): strategy固有通知は共通notifications設定との統合時に追加する。") == 1


def test_bf_literal_fixture_is_fixed_test_data():
    fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))

    assert fixture["normal_prices"] == [99.567, 100.433, 99.134, 100.866, 98.701, 101.299, 0]
    assert fixture["lots"]["entry_lot_2"] == 400.0


def test_normal_price_fixture_uses_newest_first_input_but_bf_oldest_first_math():
    from ogami_oanda.strategy.matcha_oanda import create_strategy

    strategy = create_strategy(
        _config(
            Cancel_len=1,
            std_len=4,
            dp=0,
            siguma_1=1,
            siguma_2=2,
            siguma_3=3,
            BreakOut=False,
            CTP=0,
        )
    )
    decision = strategy.decide(_strategy_input([10, 10, 99, 100, 101, 100, 100], mid=100))

    assert decision.diagnostics["price_levels"] == [99.567, 100.433, 99.134, 100.866, 98.701, 101.299, 0]
    assert decision.diagnostics["candle_order"] == "input_newest_first_math_oldest_first"


def test_breakout_direction_matches_fixed_bf_fixture():
    from ogami_oanda.strategy.matcha_oanda import create_strategy

    strategy = create_strategy(
        _config(
            std_len=3,
            pastPrice_len=2,
            dp=0,
            siguma_1=0,
            siguma_2=1,
            siguma_3=1,
            siguma_4=1,
            BreakOut=True,
            CTP=0,
        )
    )
    decision = strategy.decide(_strategy_input([100, 100, 100, 100, 100, 100, 105], mid=101))

    assert decision.diagnostics["price_levels"] == [101.0, 101.0, 101.0, 101.0, 101.0, 101.0, 1]


@pytest.mark.parametrize(
    ("closes", "mid"),
    [([100, 100, 100], 100), ([10, 10, 99, 100, 101, 100, 100], 0)],
)
def test_unready_price_calculation_never_emits_zero_price_intents(closes: list[float], mid: float):
    strategy = _normal_strategy()

    decision = strategy.decide(_strategy_input(closes, mid=mid))

    assert decision.diagnostics["price_levels"] == [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0]
    assert decision.intents == ()


def test_lot_helpers_match_fixed_bf_fixture():
    from ogami_oanda.strategy.matcha_oanda import create_strategy

    strategy = create_strategy(_config(Cancel_len=5))

    assert strategy.entry_lot_2(3000, 1000) == 400
    assert strategy.close_lot(-3000) == 600
    assert strategy.max_pos_size(1000) == 5000
    assert strategy.correction_units(7000, 5000) == 1000


def test_flat_normal_emits_protected_buy_and_sell_limits():
    decision = _normal_strategy().decide(_normal_input())

    assert [(intent.direction, intent.order_type, intent.target, intent.units) for intent in decision.intents] == [
        (Direction.BUY, OrderType.LIMIT, 99.567, 1000),
        (Direction.SELL, OrderType.LIMIT, 100.433, 1000),
    ]
    assert all(intent.take_profit == 0.02 and intent.stop_loss == 0.02 for intent in decision.intents)
    assert all(intent.order_timeout_min == 7 for intent in decision.intents)
    assert all(intent.metadata["source"] == "matcha_oanda" for intent in decision.intents)


@pytest.mark.parametrize(
    ("direction", "expected_order_direction"),
    [(Direction.BUY, Direction.BUY), (Direction.SELL, Direction.SELL)],
)
def test_normal_position_emits_only_same_direction_add_under_suppression(
    direction: Direction,
    expected_order_direction: Direction,
):
    decision = _normal_strategy().decide(_normal_input(positions=(_position(direction, 1000),)))

    assert len(decision.intents) == 1
    intent = decision.intents[0]
    assert (intent.direction, intent.order_type, intent.units) == (expected_order_direction, OrderType.LIMIT, 800)
    assert intent.target == (99.567 if direction is Direction.BUY else 100.433)
    assert intent.take_profit == 0.025
    assert intent.stop_loss == 0.025


@pytest.mark.parametrize(
    ("signal", "expected_direction"),
    [(1, Direction.BUY), (2, Direction.SELL)],
)
def test_flat_breakout_market_entry_has_fixed_amount_protection_safety_delta(
    signal: int,
    expected_direction: Direction,
):
    decision = _breakout_strategy().decide(_breakout_input(signal))

    assert len(decision.intents) == 1
    intent = decision.intents[0]
    assert (intent.direction, intent.order_type, intent.target, intent.units) == (
        expected_direction,
        OrderType.MARKET,
        0,
        1000,
    )
    assert (intent.take_profit, intent.stop_loss) == (0.02, 0.02)
    assert intent.order_timeout_min == 7


@pytest.mark.parametrize(
    ("units", "expected_take_profit", "expected_stop_loss"),
    [(1000, 0.04, 0.02), (2000, 0.02, 0.01)],
)
def test_amount_protection_distances_match_fixed_bf_literals_for_all_entries(
    units: int,
    expected_take_profit: float,
    expected_stop_loss: float,
):
    strategy = _breakout_strategy(
        LotSize=units,
        MaxLotSize=units,
        take_profit_amount=40,
        stop_loss_amount=20,
    )

    intent = strategy.decide(_breakout_input(1)).intents[0]

    assert intent.take_profit == expected_take_profit
    assert intent.stop_loss == expected_stop_loss


@pytest.mark.parametrize(
    ("position_direction", "signal", "expected_direction"),
    [(Direction.BUY, 1, Direction.BUY), (Direction.SELL, 2, Direction.SELL)],
)
def test_same_direction_breakout_adds_entry_lot_2(
    position_direction: Direction,
    signal: int,
    expected_direction: Direction,
):
    decision = _breakout_strategy().decide(
        _breakout_input(signal, positions=(_position(position_direction, 1000),))
    )

    assert decision.commands == ()
    assert [(intent.direction, intent.order_type, intent.units) for intent in decision.intents] == [
        (expected_direction, OrderType.MARKET, 800)
    ]


@pytest.mark.parametrize(
    ("position_direction", "signal", "entry_direction"),
    [(Direction.BUY, 2, Direction.SELL), (Direction.SELL, 1, Direction.BUY)],
)
def test_opposite_breakout_reduces_first_then_opens_only_reverse_remainder(
    position_direction: Direction,
    signal: int,
    entry_direction: Direction,
):
    decision = _breakout_strategy().decide(
        _breakout_input(signal, positions=(_position(position_direction, 1000),))
    )

    assert [(command.action, command.source, command.units) for command in decision.commands] == [
        (StrategyCommandAction.REDUCE_EXPOSURE, "matcha_oanda", 1000)
    ]
    assert [(intent.direction, intent.order_type, intent.units) for intent in decision.intents] == [
        (entry_direction, OrderType.MARKET, 200)
    ]
    assert decision.intents[0].take_profit == 0.1
    assert decision.intents[0].stop_loss == 0.1


@pytest.mark.parametrize("direction", [Direction.BUY, Direction.SELL])
def test_maximum_position_correction_precedes_breakout(direction: Direction):
    signal = 1 if direction is Direction.BUY else 2
    decision = _breakout_strategy().decide(
        _breakout_input(signal, positions=(_position(direction, 7000),))
    )

    assert [(command.action, command.units, command.reason) for command in decision.commands] == [
        (StrategyCommandAction.REDUCE_EXPOSURE, 1000, "maximum_exposure")
    ]
    assert decision.intents == ()


def test_max_latency_emergency_cancels_then_closes_and_excludes_entries():
    stale_time = NOW - timedelta(milliseconds=1901)
    decision = _normal_strategy().decide(
        _strategy_input(
            [10, 10, 99, 100, 101, 100, 100],
            mid=100,
            positions=(_position(Direction.BUY, 1000),),
            source_time=stale_time,
        )
    )

    assert [command.action for command in decision.commands] == [
        StrategyCommandAction.CANCEL_PENDING,
        StrategyCommandAction.CLOSE_ALL,
    ]
    assert all(command.source == "matcha_oanda" for command in decision.commands)
    assert decision.intents == ()


def test_flatten_transition_cancels_pending_and_excludes_normal_entry_that_tick():
    strategy = _normal_strategy()
    strategy.decide(_normal_input(positions=(_position(Direction.BUY, 1000),)))

    flattened = strategy.decide(_normal_input())

    assert [(command.action, command.source) for command in flattened.commands] == [
        (StrategyCommandAction.CANCEL_PENDING, "matcha_oanda")
    ]
    assert flattened.intents == ()


def test_normal_entry_runs_once_per_new_completed_m1_candle():
    strategy = _normal_strategy()
    first_input = _normal_input()

    first = strategy.decide(first_input)
    duplicate = strategy.decide(first_input)
    next_candles = _newest_first_candles([10, 99, 100, 101, 100, 100, 100])
    next_candles[0]["time"] = (NOW + timedelta(minutes=1)).isoformat()
    next_candle = strategy.decide(
        StrategyInput(first_input.quote, candles=next_candles, evaluation_time=NOW)
    )

    assert len(first.intents) == 2
    assert duplicate.intents == ()
    assert len(next_candle.intents) == 2


def test_equivalent_utc_candle_spelling_after_restore_does_not_duplicate_normal_entry():
    strategy = _normal_strategy()
    strategy.decide(_normal_input())
    state = strategy.dump_state()
    state["last_candle"] = "2026-08-27T11:06:00Z"
    restored = _normal_strategy()
    restored.load_state(state)

    duplicate = restored.decide(_normal_input())

    assert duplicate.intents == ()
    assert restored.dump_state()["last_candle"] == "2026-08-27T11:06:00+00:00"


def test_older_out_of_order_candle_never_emits_or_regresses_last_candle_state():
    strategy = _normal_strategy()
    strategy.decide(_normal_input())
    older_candles = _newest_first_candles([10, 10, 99, 100, 101, 100, 100])
    older_candles[0]["time"] = "2026-08-27T11:05:00+00:00"

    older = strategy.decide(
        StrategyInput(_normal_input().quote, candles=older_candles, evaluation_time=NOW)
    )

    assert older.intents == ()
    assert strategy.dump_state()["last_candle"] == "2026-08-27T11:06:00+00:00"


@pytest.mark.parametrize(
    "invalid_timestamp",
    ["not-a-time", "2026-08-27T11:06:30+00:00", "2026-08-27T11:06:00"],
)
def test_invalid_naive_or_non_m1_candle_timestamp_suppresses_normal_entry(
    invalid_timestamp: str,
):
    strategy = _normal_strategy()
    candles = _newest_first_candles([10, 10, 99, 100, 101, 100, 100])
    candles[0]["time"] = invalid_timestamp

    decision = strategy.decide(
        StrategyInput(_normal_input().quote, candles=candles, evaluation_time=NOW)
    )

    assert decision.intents == ()
    assert strategy.dump_state()["last_candle"] is None


def test_breakout_risk_is_evaluated_on_every_tick_even_on_same_candle():
    strategy = _breakout_strategy()
    strategy_input = _breakout_input(1)

    first = strategy.decide(strategy_input)
    second = strategy.decide(strategy_input)

    assert [intent.order_type for intent in first.intents] == [OrderType.MARKET]
    assert [intent.order_type for intent in second.intents] == [OrderType.MARKET]


@pytest.mark.parametrize(
    "input_overrides",
    [
        {"source_time": None},
        {"evaluation_time": None},
        {"tradeable": False},
        {"source_time": NOW - timedelta(milliseconds=101)},
    ],
)
def test_unknown_stale_or_untradeable_quote_suppresses_new_intent_and_consumes_candle(
    input_overrides: dict[str, object],
):
    strategy = _normal_strategy(stop_latency=100, max_latency=200)
    closes = [10, 10, 99, 100, 101, 100, 100]

    suppressed = strategy.decide(_strategy_input(closes, mid=100, **input_overrides))
    fresh_same_candle = strategy.decide(_strategy_input(closes, mid=100))

    assert suppressed.commands == ()
    assert suppressed.intents == ()
    assert fresh_same_candle.intents == ()


def test_state_caps_latency_samples_and_round_trips_all_restart_fields():
    strategy = _normal_strategy(stop_latency=1_000_000, max_latency=1_000_000)
    long_position = (_position(Direction.BUY, 1000),)
    for age_ms in range(105):
        strategy.decide(
            _strategy_input(
                [10, 10, 99, 100, 101, 100, 100],
                mid=100,
                positions=long_position,
                source_time=NOW - timedelta(milliseconds=age_ms),
            )
        )

    state = strategy.dump_state()
    serialized = json.loads(json.dumps(state))

    assert serialized["version"] == 1
    assert serialized["source"] == "matcha_oanda"
    assert serialized["last_candle"] == "2026-08-27T11:06:00+00:00"
    assert serialized["previous_net_units"] == 1000
    assert serialized["cooldown_minute"] == "2026-08-27T12:00:00+00:00"
    assert serialized["latency_samples_ms"] == [float(value) for value in range(5, 105)]

    restored = _normal_strategy(stop_latency=1_000_000, max_latency=1_000_000)
    restored.load_state(serialized)
    assert restored.dump_state() == serialized


def test_restore_prevents_duplicate_normal_order_and_preserves_flatten_cleanup():
    long_position = (_position(Direction.BUY, 1000),)
    strategy = _normal_strategy()
    strategy.decide(_normal_input(positions=long_position))
    restored = _normal_strategy()
    restored.load_state(json.loads(json.dumps(strategy.dump_state())))

    duplicate = restored.decide(_normal_input(positions=long_position))
    flattened = restored.decide(_normal_input())

    assert duplicate.intents == ()
    assert [command.action for command in flattened.commands] == [StrategyCommandAction.CANCEL_PENDING]
    assert flattened.intents == ()


@pytest.mark.parametrize(
    "invalid_state",
    [
        {"version": 2, "source": "matcha_oanda", "last_candle": None, "previous_net_units": 0, "cooldown_minute": None, "latency_samples_ms": []},
        {"version": 1, "source": "other", "last_candle": None, "previous_net_units": 0, "cooldown_minute": None, "latency_samples_ms": []},
        {"version": 1, "source": "matcha_oanda", "last_candle": 1, "previous_net_units": 0, "cooldown_minute": None, "latency_samples_ms": []},
        {"version": 1, "source": "matcha_oanda", "last_candle": None, "previous_net_units": True, "cooldown_minute": None, "latency_samples_ms": []},
        {"version": 1, "source": "matcha_oanda", "last_candle": "not-a-time", "previous_net_units": 0, "cooldown_minute": None, "latency_samples_ms": []},
        {"version": 1, "source": "matcha_oanda", "last_candle": "2026-08-27T11:06:30+00:00", "previous_net_units": 0, "cooldown_minute": None, "latency_samples_ms": []},
        {"version": 1, "source": "matcha_oanda", "last_candle": "2026-08-27T11:06:00", "previous_net_units": 0, "cooldown_minute": None, "latency_samples_ms": []},
        {"version": 1, "source": "matcha_oanda", "last_candle": None, "previous_net_units": 0, "cooldown_minute": "not-a-time", "latency_samples_ms": []},
        {"version": 1, "source": "matcha_oanda", "last_candle": None, "previous_net_units": 0, "cooldown_minute": None, "latency_samples_ms": [-1]},
        {"version": 1, "source": "matcha_oanda", "last_candle": None, "previous_net_units": 0, "cooldown_minute": None, "latency_samples_ms": [0.0] * 101},
    ],
)
def test_state_validation_rejects_malformed_restart_data(invalid_state: dict[str, object]):
    strategy = _normal_strategy()

    with pytest.raises(ValueError, match="state"):
        strategy.load_state(invalid_state)
