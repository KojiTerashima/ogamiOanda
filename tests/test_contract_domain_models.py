from types import SimpleNamespace

import pytest

import fGeneric as legacy_generic
from ogami_oanda.adapters.legacy.order_dict import (
    legacy_dict_to_order_plan,
    order_plan_to_legacy_dict,
)
from ogami_oanda.adapters.legacy.position_dict import (
    legacy_position_to_snapshot,
    snapshot_to_legacy_position,
)
from ogami_oanda.domain.market.candle_frame import CandleFrameSchema
from ogami_oanda.domain.market.currency_pair import currency_pair
from ogami_oanda.domain.positions.models import OrderState, TradeState


@pytest.mark.contract
@pytest.mark.parametrize("pair_name", ["USD_JPY", "EUR_USD", "AUD_USD"])
def test_new_currency_pair_matches_legacy_contract(pair_name):
    new_pair = currency_pair(pair_name)
    legacy_pair = legacy_generic.currency_pair(pair_name)

    assert new_pair.pip_value == legacy_pair.pip_value
    assert new_pair.round_keta == legacy_pair.round_keta
    assert new_pair.pips_to_price(10) == legacy_pair.pips_to_price(10)
    assert new_pair.price_to_pips(new_pair.pips_to_price(10)) == 10


@pytest.mark.contract
def test_legacy_order_plan_round_trip_preserves_execution_fields():
    legacy_plan = {
        "decision_time": "2026/01/02 03:04:05",
        "units": 10000,
        "pair": "EUR_USD",
        "direction": -1,
        "target_price": 1.101,
        "lc_price": 1.102,
        "lc_range": 0.001,
        "tp_price": 1.099,
        "tp_range": 0.002,
        "type": "LIMIT",
        "name": "baseline",
        "name_ymdhms": "baseline_2026/01/02 03:04:05",
        "oa_mode": 2,
        "order_timeout_min": 45,
        "trade_timeout_min": 240,
        "order_permission": True,
        "priority": 5,
        "watching_price": 0,
        "lc_change": [{"exe": False}],
        "move_ave": 0.12,
        "candle_lc_change_type": "M5",
        "memo": "fixture",
    }

    round_tripped = order_plan_to_legacy_dict(legacy_dict_to_order_plan(legacy_plan))

    for key in (
        "decision_time",
        "units",
        "pair",
        "direction",
        "target_price",
        "lc_price",
        "lc_range",
        "tp_price",
        "tp_range",
        "type",
        "name",
        "oa_mode",
        "order_timeout_min",
        "trade_timeout_min",
        "order_permission",
        "priority",
        "lc_change",
        "move_ave",
        "memo",
    ):
        assert round_tripped[key] == legacy_plan[key]

    payload = round_tripped["for_api_json"]["order"]
    assert payload["instrument"] == "EUR_USD"
    assert payload["units"] == "-10000"
    assert payload["price"] == "1.101"


@pytest.mark.contract
def test_position_mapper_preserves_observable_state():
    legacy_position = SimpleNamespace(
        name="baseline",
        pair="USD_JPY",
        o_state="PENDING",
        t_state="OPEN",
        o_id=123,
        t_id=456,
        life=True,
        waiting_order=False,
    )

    snapshot = legacy_position_to_snapshot(legacy_position)

    assert snapshot.order_state is OrderState.PENDING
    assert snapshot.trade_state is TradeState.OPEN
    assert snapshot_to_legacy_position(snapshot) == {
        "name": "baseline",
        "pair": "USD_JPY",
        "o_state": "PENDING",
        "t_state": "OPEN",
        "o_id": "123",
        "t_id": "456",
        "life": True,
        "waiting_order": False,
    }


@pytest.mark.contract
def test_candle_frame_schema_requires_reversed_time_order(candle_frame):
    schema = CandleFrameSchema(pair="USD_JPY", granularity="M5")

    schema.validate(candle_frame)
    with pytest.raises(ValueError, match="newest to oldest"):
        schema.validate(candle_frame.iloc[::-1].reset_index(drop=True))
