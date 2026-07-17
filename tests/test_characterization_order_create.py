from dataclasses import dataclass, field

import pytest

from classOrderCreate import Order


@dataclass
class _CandleMeta:
    def cal_move_ave(self, times):
        return 0.12


@dataclass
class _CandleAnalysis:
    candle_meta_class: _CandleMeta = field(default_factory=_CandleMeta)


@pytest.mark.characterization
@pytest.mark.parametrize(
    ("pair", "current_price", "order_type", "direction", "target", "tp", "lc", "expected"),
    [
        (
            "USD_JPY",
            150.0,
            "STOP",
            1,
            0.1,
            0.2,
            0.1,
            {"target_price": 150.1, "tp_price": 150.3, "lc_price": 150.0, "units": "10000"},
        ),
        (
            "EUR_USD",
            1.1,
            "LIMIT",
            -1,
            0.001,
            0.002,
            0.001,
            {"target_price": 1.101, "tp_price": 1.099, "lc_price": 1.102, "units": "-10000"},
        ),
        (
            "AUD_USD",
            0.7,
            "MARKET",
            1,
            0.005,
            0.003,
            0.002,
            {"target_price": 0.7, "tp_price": 0.703, "lc_price": 0.698, "units": "10000"},
        ),
    ],
)
def test_order_plan_and_oanda_payload_contract(
    pair,
    current_price,
    order_type,
    direction,
    target,
    tp,
    lc,
    expected,
):
    order = Order(
        {
            "name": "baseline",
            "current_price": current_price,
            "target": target,
            "direction": direction,
            "type": order_type,
            "tp": tp,
            "lc": lc,
            "units": 10000,
            "priority": 5,
            "decision_time": "2026/01/02 03:04:05",
            "pair": pair,
            "order_timeout_min": 45,
            "lc_change": [],
            "candle_analysis_class": _CandleAnalysis(),
        }
    )

    plan = order.exe_order_plan
    payload = plan["for_api_json"]["order"]

    assert {key: plan[key] for key in ("target_price", "tp_price", "lc_price")} == {
        key: expected[key] for key in ("target_price", "tp_price", "lc_price")
    }
    assert plan["pair"] == pair
    assert plan["order_timeout_min"] == 45
    assert plan["priority"] == 5
    assert payload["instrument"] == pair
    assert payload["units"] == expected["units"]
    assert payload["type"] == order_type
