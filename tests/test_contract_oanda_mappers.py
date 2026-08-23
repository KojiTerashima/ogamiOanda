import pytest
import pandas as pd

from ogami_oanda.adapters.oanda.mappers import (
    broker_request_to_oanda,
    map_candle_response,
    map_order_cancel_response,
    map_order_create_response,
    map_order_snapshot,
    map_price_response,
    map_trade_close_response,
    map_trade_protection_response,
    map_trade_snapshot,
)
from ogami_oanda.application.ports.broker import OrderSubmissionState
from ogami_oanda.domain.orders.models import BrokerOrderRequest, OrderType


@pytest.mark.contract
def test_oanda_price_response_mapping_rounds_by_pair():
    response = {"prices": [{"bids": [{"price": "150.1234"}], "asks": [{"price": "150.1456"}]}]}

    assert map_price_response("USD_JPY", response) == {
        "bid": 150.123,
        "ask": 150.146,
        "mid": 150.135,
        "spread": 0.023,
        "tradeable": True,
    }


@pytest.mark.contract
def test_oanda_candle_response_maps_to_canonical_jst_ohlc_newest_first():
    frame = map_candle_response(
        {
            "candles": [
                {"time": "2026-01-02T00:00:00.000000000Z", "complete": True, "volume": 12, "mid": {"o": "150.1", "c": "150.2", "h": "150.3", "l": "150.0"}},
                {"time": "2026-01-02T00:05:00.000000000Z", "complete": False, "volume": 3, "mid": {"o": "150.2", "c": "150.25", "h": "150.4", "l": "150.1"}},
            ]
        }
    )

    assert list(frame.columns) == ["time_jp", "time_jp_dt", "open", "close", "high", "low", "volume", "time"]
    assert frame.iloc[0].to_dict() == {
        "time_jp": "2026/01/02 09:05:00",
        "time_jp_dt": pd.Timestamp("2026-01-02 09:05:00"),
        "open": 150.2,
        "close": 150.25,
        "high": 150.4,
        "low": 150.1,
        "volume": 3,
        "time": "2026-01-02T00:05:00.000000000Z",
    }


@pytest.mark.contract
def test_broker_request_maps_to_oanda_payload():
    request = BrokerOrderRequest("EUR_USD", -10000, OrderType.LIMIT, 1.101, 1.099, 1.102)

    assert broker_request_to_oanda(request) == {
        "order": {
            "instrument": "EUR_USD",
            "units": "-10000",
            "type": "LIMIT",
            "timeInForce": "GTC",
            "positionFill": "DEFAULT",
            "price": "1.101",
            "takeProfitOnFill": {"timeInForce": "GTC", "price": "1.099"},
            "stopLossOnFill": {"timeInForce": "GTC", "price": "1.102"},
        }
    }


@pytest.mark.contract
@pytest.mark.parametrize(
    ("pair_name", "price", "take_profit", "stop_loss", "expected_prices"),
    [
        ("USD_JPY", 150.1234, 150.3234, 150.0234, ("150.123", "150.323", "150.023")),
        ("EUR_USD", 1.101234, 1.103234, 1.100234, ("1.10123", "1.10323", "1.10023")),
        ("AUD_USD", 0.651234, 0.653234, 0.650234, ("0.65123", "0.65323", "0.65023")),
    ],
)
@pytest.mark.parametrize("order_type", [OrderType.MARKET, OrderType.LIMIT, OrderType.STOP])
def test_broker_request_maps_three_pairs_and_order_types_to_oanda_wire_contract(
    pair_name,
    price,
    take_profit,
    stop_loss,
    expected_prices,
    order_type,
):
    request = BrokerOrderRequest(pair_name, -123, order_type, price, take_profit, stop_loss)

    order = broker_request_to_oanda(request)["order"]

    expected_price, expected_take_profit, expected_stop_loss = expected_prices
    assert order["instrument"] == pair_name
    assert order["units"] == "-123"
    assert order["type"] == order_type.value
    assert order["positionFill"] == "DEFAULT"
    assert order["timeInForce"] == ("FOK" if order_type is OrderType.MARKET else "GTC")
    if order_type is OrderType.MARKET:
        assert "price" not in order
    else:
        assert order["price"] == expected_price
    assert order["takeProfitOnFill"] == {
        "timeInForce": "GTC",
        "price": expected_take_profit,
    }
    assert order["stopLossOnFill"] == {
        "timeInForce": "GTC",
        "price": expected_stop_loss,
    }


@pytest.mark.contract
def test_oanda_client_extensions_are_opt_in_and_use_stable_reference():
    request = BrokerOrderRequest(
        "USD_JPY",
        100,
        OrderType.LIMIT,
        150.0,
        150.2,
        149.9,
        client_reference="ogm-0123456789abcdef0123",
    )

    default_order = broker_request_to_oanda(request)["order"]
    opted_in_order = broker_request_to_oanda(
        request,
        include_client_extensions=True,
    )["order"]

    assert "clientExtensions" not in default_order
    assert "tradeClientExtensions" not in default_order
    assert opted_in_order["clientExtensions"] == {
        "id": "ogm-0123456789abcdef0123",
        "tag": "ogami-oanda",
    }
    assert opted_in_order["tradeClientExtensions"] == {
        "id": "ogm-0123456789abcdef0123",
        "tag": "ogami-oanda",
    }


@pytest.mark.contract
def test_order_response_mapping_distinguishes_rejection():
    pending = map_order_create_response({"orderCreateTransaction": {"id": "123"}})
    filled = map_order_create_response(
        {
            "orderCreateTransaction": {"id": "124"},
            "orderFillTransaction": {
                "orderID": "124",
                "price": "150.125",
                "tradeOpened": {"tradeID": "trade-1", "price": "150.125"},
            },
        }
    )
    rejected = map_order_create_response(
        {"orderRejectTransaction": {"rejectReason": "PRICE_INVALID"}}
    )
    cancelled = map_order_create_response(
        {"orderCancelTransaction": {"orderID": "125", "reason": "MARKET_HALTED"}}
    )
    terminal = map_order_create_response(
        {
            "orderCreateTransaction": {"id": "126"},
            "orderFillTransaction": {
                "orderID": "126",
                "tradeReduced": {"tradeID": "existing-trade"},
            },
        }
    )
    closed_multiple = map_order_create_response(
        {
            "orderFillTransaction": {
                "orderID": "127",
                "tradesClosed": [
                    {"tradeID": "existing-1"},
                    {"tradeID": "existing-2"},
                ],
            },
        }
    )
    unknown = map_order_create_response({})

    assert (pending.state, pending.order_id) == (OrderSubmissionState.PENDING, "123")
    assert (filled.state, filled.order_id, filled.trade_id, filled.fill_price) == (
        OrderSubmissionState.FILLED,
        "124",
        "trade-1",
        150.125,
    )
    assert (rejected.state, rejected.reason) == (
        OrderSubmissionState.REJECTED,
        "PRICE_INVALID",
    )
    assert (cancelled.state, cancelled.order_id, cancelled.reason) == (
        OrderSubmissionState.CANCELLED,
        "125",
        "MARKET_HALTED",
    )
    assert (terminal.state, terminal.affected_trade_ids) == (
        OrderSubmissionState.TERMINAL,
        ("existing-trade",),
    )
    assert closed_multiple.affected_trade_ids == ("existing-1", "existing-2")
    assert unknown.state is OrderSubmissionState.UNKNOWN


@pytest.mark.contract
def test_execution_response_mappers_require_action_specific_confirmation():
    assert map_order_cancel_response(
        {"orderCancelTransaction": {"id": "tx-1", "orderID": "order-1"}},
        "order-1",
    ) == (True, "order-1", "")
    assert map_trade_close_response(
        {"orderFillTransaction": {"tradesClosed": [{"tradeID": "trade-1"}]}},
        "trade-1",
    ) == (True, "trade-1", "")
    assert map_trade_close_response(
        {"orderCancelTransaction": {"reason": "MARKET_HALTED"}},
        "trade-1",
    ) == (False, None, "MARKET_HALTED")
    assert map_trade_protection_response(
        {"stopLossOrderTransaction": {"id": "sl-1", "tradeID": "trade-1"}},
        "trade-1",
    ) == (True, "trade-1", "")


@pytest.mark.contract
def test_order_and_trade_snapshots_preserve_broker_lifecycle_state():
    order = map_order_snapshot(
        {
            "order": {
                "id": "order-1",
                "instrument": "USD_JPY",
                "state": "FILLED",
                "tradeOpenedID": "trade-1",
                "units": "1000",
                "price": "150.10",
                "clientExtensions": {
                    "id": "ogm-order-reference",
                    "tag": "ogami-oanda",
                },
            }
        }
    )
    trade = map_trade_snapshot(
        {
            "trade": {
                "id": "trade-1",
                "instrument": "USD_JPY",
                "state": "CLOSED",
                "currentUnits": "-500",
                "price": "149.80",
                "stopLossOrder": {"price": "149.95"},
                "clientExtensions": {
                    "id": "ogm-trade-reference",
                    "tag": "ogami-oanda",
                },
            }
        }
    )

    assert order is not None
    assert order.order_id == "order-1"
    assert order.trade_id == "trade-1"
    assert order.life is True
    assert order.direction == 1
    assert order.target_price == 150.1
    assert order.units == 1000
    assert order.name == "ogami-oanda"
    assert order.client_reference == "ogm-order-reference"
    assert trade is not None
    assert trade.trade_id == "trade-1"
    assert trade.trade_state.value == "CLOSED"
    assert trade.life is False
    assert trade.direction == -1
    assert trade.target_price == 149.8
    assert trade.units == 500
    assert trade.current_stop_loss == 149.95
    assert trade.name == "ogami-oanda"
    assert trade.client_reference == "ogm-trade-reference"
