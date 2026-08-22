from types import SimpleNamespace

import pytest
from oandapyV20.endpoints.instruments import InstrumentsCandles
from oandapyV20.endpoints.orders import OrderCancel, OrderCreate, OrderDetails, OrdersPending
from oandapyV20.endpoints.pricing import PricingInfo
from oandapyV20.endpoints.trades import OpenTrades, TradeCRCDO, TradeClose, TradeDetails
from oandapyV20.exceptions import V20Error

from ogami_oanda.adapters.oanda.client import OandaClient
from ogami_oanda.adapters.oanda.execution import OandaExecutionAdapter
from ogami_oanda.adapters.oanda.market_data import OandaMarketDataAdapter
from ogami_oanda.adapters.oanda.query import OandaQueryAdapter
from ogami_oanda.application.ports.broker import BrokerExecutionPort, BrokerQueryPort
from ogami_oanda.application.ports.market_data import MarketDataPort
from ogami_oanda.domain.orders.models import BrokerOrderRequest, OrderType


class _Api:
    def __init__(self):
        self.endpoints = []

    def request(self, endpoint):
        self.endpoints.append(endpoint)
        return {"endpoint": endpoint.__class__.__name__}


class _Client:
    account_id = "account-1"

    def __init__(self):
        self.endpoints = []

    def request(self, endpoint):
        self.endpoints.append(endpoint)
        if isinstance(endpoint, PricingInfo):
            return {"prices": [{"bids": [{"price": "150.10"}], "asks": [{"price": "150.12"}]}]}
        if isinstance(endpoint, InstrumentsCandles):
            return {
                "candles": [
                    {
                        "time": "2026-01-02T00:00:00.000000000Z",
                        "mid": {"o": "150.0", "c": "150.1", "h": "150.2", "l": "149.9"},
                    }
                ]
            }
        if isinstance(endpoint, OrderCreate):
            return {"orderCreateTransaction": {"id": "created-1"}}
        if isinstance(endpoint, OrderCancel):
            return {
                "orderCancelTransaction": {
                    "id": "cancel-transaction-1",
                    "orderID": "order-1",
                    "reason": "CLIENT_REQUEST",
                },
                "relatedTransactionIDs": ["cancel-transaction-1"],
                "lastTransactionID": "cancel-transaction-1",
            }
        if isinstance(endpoint, TradeClose):
            return {
                "orderCreateTransaction": {"id": "close-order-1"},
                "orderFillTransaction": {
                    "id": "close-fill-1",
                    "tradesClosed": [{"tradeID": "trade-1", "units": "100"}],
                },
                "relatedTransactionIDs": ["close-order-1", "close-fill-1"],
                "lastTransactionID": "close-fill-1",
            }
        if isinstance(endpoint, TradeCRCDO):
            return {
                "takeProfitOrderTransaction": {"id": "tp-1", "tradeID": "trade-1"},
                "stopLossOrderTransaction": {"id": "sl-1", "tradeID": "trade-1"},
                "relatedTransactionIDs": ["tp-1", "sl-1"],
                "lastTransactionID": "sl-1",
            }
        if isinstance(endpoint, OrderDetails):
            return {
                "order": {
                    "id": "order-1",
                    "instrument": "USD_JPY",
                    "state": "PENDING",
                    "units": "1000",
                    "price": "150.0",
                }
            }
        if isinstance(endpoint, OrdersPending):
            return {
                "orders": [
                    {
                        "id": "order-2",
                        "instrument": "USD_JPY",
                        "state": "PENDING",
                        "units": "-500",
                        "price": "150.2",
                    }
                ]
            }
        if isinstance(endpoint, TradeDetails):
            return {
                "trade": {
                    "id": "trade-1",
                    "instrument": "USD_JPY",
                    "state": "OPEN",
                    "currentUnits": "1000",
                    "price": "150.0",
                }
            }
        if isinstance(endpoint, OpenTrades):
            return {
                "trades": [
                    {
                        "id": "trade-2",
                        "instrument": "EUR_USD",
                        "state": "OPEN",
                        "currentUnits": "-250",
                        "price": "1.105",
                        "stopLossOrder": {"price": "1.11"},
                    }
                ]
            }
        return {}


@pytest.mark.contract
def test_oanda_client_wraps_injected_api_without_importing_runtime_configuration():
    api = _Api()
    account = SimpleNamespace(account_id="account-1", access_token="secret", environment="practice")
    client = OandaClient(account, api=api)

    endpoint = SimpleNamespace()

    assert client.account_id == "account-1"
    assert client.request(endpoint) == {"endpoint": "SimpleNamespace"}
    assert api.endpoints == [endpoint]


@pytest.mark.contract
def test_market_data_adapter_satisfies_port_and_maps_quote_and_candles():
    client = _Client()
    adapter = OandaMarketDataAdapter(client)

    quote = adapter.current_quote("USD_JPY")
    frame = adapter.candles("USD_JPY", "M5", 1)

    assert isinstance(adapter, MarketDataPort)
    assert quote.mid == 150.11
    assert quote.spread == pytest.approx(0.02)
    assert frame.iloc[0]["time_jp"] == "2026/01/02 09:00:00"
    assert isinstance(client.endpoints[0], PricingInfo)
    assert isinstance(client.endpoints[1], InstrumentsCandles)


@pytest.mark.contract
def test_execution_adapter_builds_oanda_endpoints_behind_broker_port():
    client = _Client()
    adapter = OandaExecutionAdapter(client)
    request = BrokerOrderRequest("USD_JPY", -500, OrderType.LIMIT, 150.1, 149.9, 150.2)

    assert isinstance(adapter, BrokerExecutionPort)
    assert adapter.submit(request).reference_id == "created-1"
    cancel = adapter.cancel_order("order-1")
    close = adapter.close_trade("trade-1", 100)
    amend = adapter.amend_protection("trade-1", 150.3, 149.8)

    assert [type(endpoint) for endpoint in client.endpoints] == [
        OrderCreate,
        OrderCancel,
        TradeClose,
        TradeCRCDO,
    ]
    assert (cancel.accepted, cancel.reference_id, cancel.message) == (True, "order-1", "")
    assert (close.accepted, close.reference_id, close.message) == (True, "trade-1", "")
    assert (amend.accepted, amend.reference_id, amend.message) == (True, "trade-1", "")


class _MutationClient:
    account_id = "account-1"

    def __init__(self, responses):
        self.responses = iter(responses)

    def request(self, endpoint):
        response = next(self.responses)
        if isinstance(response, Exception):
            raise response
        return response


@pytest.mark.contract
def test_execution_adapter_maps_oanda_rejection_responses_to_application_results():
    adapter = OandaExecutionAdapter(
        _MutationClient(
            [
                {
                    "errorCode": "NO_SUCH_ORDER",
                    "errorMessage": "The order does not exist",
                },
                {
                    "orderCreateTransaction": {"id": "close-order-1"},
                    "orderCancelTransaction": {
                        "id": "close-cancel-1",
                        "reason": "MARKET_HALTED",
                    },
                },
                {
                    "stopLossOrderRejectTransaction": {
                        "id": "sl-reject-1",
                        "rejectReason": "STOP_LOSS_ON_FILL_PRICE_DISTANCE_MAXIMUM_EXCEEDED",
                    }
                },
            ]
        )
    )

    cancel = adapter.cancel_order("missing-order")
    close = adapter.close_trade("trade-1")
    amend = adapter.amend_protection("trade-1", None, 149.8)

    assert (cancel.accepted, cancel.reference_id, cancel.message) == (
        False,
        None,
        "NO_SUCH_ORDER: The order does not exist",
    )
    assert (close.accepted, close.reference_id, close.message) == (
        False,
        None,
        "MARKET_HALTED",
    )
    assert (amend.accepted, amend.reference_id, amend.message) == (
        False,
        None,
        "STOP_LOSS_ON_FILL_PRICE_DISTANCE_MAXIMUM_EXCEEDED",
    )


@pytest.mark.contract
def test_execution_adapter_normalizes_oanda_api_exceptions_as_rejections():
    error_payload = '{"errorCode":"NO_SUCH_TRADE","errorMessage":"The trade does not exist"}'
    adapter = OandaExecutionAdapter(
        _MutationClient(
            [
                V20Error(404, error_payload),
                V20Error(404, error_payload),
                V20Error(404, error_payload),
            ]
        )
    )

    results = (
        adapter.cancel_order("order-1"),
        adapter.close_trade("trade-1"),
        adapter.amend_protection("trade-1", None, 149.8),
    )

    assert all(result.accepted is False for result in results)
    assert all(result.reference_id is None for result in results)
    assert {result.message for result in results} == {
        "NO_SUCH_TRADE: The trade does not exist"
    }


@pytest.mark.contract
def test_query_adapter_maps_pending_and_open_runtime_state_behind_query_port():
    client = _Client()
    adapter = OandaQueryAdapter(client)

    order = adapter.order("order-1")
    trade = adapter.trade("trade-1")
    pending = adapter.pending_orders()
    opened = adapter.open_positions()

    assert isinstance(adapter, BrokerQueryPort)
    assert order is not None and order.order_id == "order-1"
    assert trade is not None and trade.trade_id == "trade-1"
    assert pending[0].direction == -1
    assert opened[0].pair == "EUR_USD"
    assert opened[0].direction == -1
    assert opened[0].target_price == 1.105
    assert opened[0].current_stop_loss == 1.11
