import pytest

from ogami_oanda.adapters.oanda.mappers import (
    broker_request_to_oanda,
    map_candle_response,
    map_order_create_response,
    map_order_snapshot,
    map_price_response,
    map_trade_snapshot,
)
from ogami_oanda.domain.orders.models import BrokerOrderRequest, OrderType


@pytest.mark.contract
def test_oanda_price_response_mapping_rounds_by_pair():
    response = {"prices": [{"bids": [{"price": "150.1234"}], "asks": [{"price": "150.1456"}]}]}

    assert map_price_response("USD_JPY", response) == {
        "bid": 150.123,
        "ask": 150.146,
        "mid": 150.135,
        "spread": 0.023,
    }


@pytest.mark.contract
def test_oanda_candle_response_mapping_preserves_raw_candles():
    frame = map_candle_response({"candles": [{"time": "2026-01-02T00:00:00.000000000Z", "complete": True}]})

    assert list(frame.columns) == ["time", "complete"]
    assert len(frame) == 1


@pytest.mark.contract
def test_broker_request_maps_to_oanda_payload():
    request = BrokerOrderRequest("EUR_USD", -10000, OrderType.LIMIT, 1.101, 1.099, 1.102)

    assert broker_request_to_oanda(request) == {
        "order": {
            "instrument": "EUR_USD",
            "units": "-10000",
            "type": "LIMIT",
            "positionFill": "DEFAULT",
            "price": "1.101",
            "takeProfitOnFill": {"timeInForce": "GTC", "price": "1.099"},
            "stopLossOnFill": {"timeInForce": "GTC", "price": "1.102"},
        }
    }


@pytest.mark.contract
def test_order_response_mapping_distinguishes_rejection():
    assert map_order_create_response({"orderCreateTransaction": {"id": "123"}}) == (True, "123")
    assert map_order_create_response({"orderCancelTransaction": {"id": "124"}}) == (False, None)


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
    assert trade is not None
    assert trade.trade_id == "trade-1"
    assert trade.trade_state.value == "CLOSED"
    assert trade.life is False
    assert trade.direction == -1
    assert trade.target_price == 149.8
    assert trade.units == 500
    assert trade.current_stop_loss == 149.95
