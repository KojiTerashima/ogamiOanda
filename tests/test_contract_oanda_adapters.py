from types import SimpleNamespace
from oandapyV20.endpoints.accounts import AccountInstruments, AccountSummary

import pytest
from oandapyV20.endpoints.instruments import InstrumentsCandles
from oandapyV20.endpoints.orders import OrderCancel, OrderCreate, OrderDetails, OrdersPending
from oandapyV20.endpoints.pricing import PricingInfo
from oandapyV20.endpoints.trades import OpenTrades, TradeCRCDO, TradeClose, TradeDetails
from oandapyV20.endpoints.transactions import TransactionsSinceID
from oandapyV20.exceptions import V20Error

from ogami_oanda.adapters.oanda.client import OandaClient
from ogami_oanda.adapters.oanda.execution import OandaExecutionAdapter
from ogami_oanda.adapters.oanda.market_data import OandaMarketDataAdapter
from ogami_oanda.adapters.oanda.query import OandaQueryAdapter
from ogami_oanda.application.ports.broker import (
    BrokerExecutionPort,
    BrokerQueryPort,
    MutationState,
    OrderSubmissionState,
)
from ogami_oanda.application.ports.market_data import MarketDataPort
from ogami_oanda.application.errors import TransientExternalServiceError
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
        if isinstance(endpoint, AccountSummary):
            return {
                "account": {
                    "id": "account-1",
                    "hedgingEnabled": True,
                },
                "lastTransactionID": "100",
            }
        if isinstance(endpoint, TransactionsSinceID):
            return {
                "lastTransactionID": "103",
                "transactions": [
                    {
                        "id": "101",
                        "type": "LIMIT_ORDER",
                        "time": "2026-01-02T01:00:01.000000000Z",
                        "instrument": "USD_JPY",
                        "units": "100",
                        "price": "150.1",
                        "clientExtensions": {"id": "ogm-reference"},
                    },
                    {
                        "id": "102",
                        "type": "ORDER_FILL",
                        "orderID": "101",
                        "instrument": "USD_JPY",
                        "units": "100",
                        "tradeOpened": {
                            "tradeID": "trade-1",
                            "price": "150.11",
                        },
                    },
                ],
            }
        if isinstance(endpoint, PricingInfo):
            return {
                "prices": [
                    {
                        "bids": [{"price": "150.10"}],
                        "asks": [{"price": "150.12"}],
                        "status": "tradeable",
                    }
                ]
            }
        if isinstance(endpoint, AccountInstruments):
            return {
                "instruments": [
                    {
                        "name": "USD_JPY",
                        "minimumTradeSize": "1",
                        "maximumOrderUnits": "1000000",
                        "tradeUnitsPrecision": 0,
                    }
                ],
                "lastTransactionID": "104",
            }
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
@pytest.mark.parametrize(
    ("error", "retry_after"),
    [
        (TimeoutError("timed out"), None),
        (V20Error(429, '{"errorCode":"RATE_LIMIT","errorMessage":"Slow down"}'), None),
        (V20Error(503, '{"errorCode":"SERVICE_UNAVAILABLE","errorMessage":"Retry"}'), None),
    ],
)
def test_oanda_client_translates_only_known_transient_failures(error, retry_after):
    class _FailingApi:
        def request(self, endpoint):
            del endpoint
            raise error

    client = OandaClient(
        SimpleNamespace(
            account_id="account-1",
            access_token="secret",
            environment="practice",
        ),
        api=_FailingApi(),
    )

    with pytest.raises(TransientExternalServiceError) as error_info:
        client.request(SimpleNamespace())

    assert error_info.value.service == "oanda"
    assert error_info.value.retry_after_seconds == retry_after


@pytest.mark.contract
def test_oanda_client_does_not_hide_permanent_or_programming_errors():
    class _FailingApi:
        def __init__(self, error):
            self.error = error

        def request(self, endpoint):
            del endpoint
            raise self.error

    account = SimpleNamespace(
        account_id="account-1",
        access_token="secret",
        environment="practice",
    )

    with pytest.raises(V20Error):
        OandaClient(
            account,
            api=_FailingApi(V20Error(401, "unauthorized")),
        ).request(SimpleNamespace())
    with pytest.raises(ValueError, match="programming defect"):
        OandaClient(
            account,
            api=_FailingApi(ValueError("programming defect")),
        ).request(SimpleNamespace())


@pytest.mark.contract
def test_market_data_adapter_satisfies_port_and_maps_quote_and_candles():
    client = _Client()
    adapter = OandaMarketDataAdapter(client)

    quote = adapter.current_quote("USD_JPY")
    frame = adapter.candles("USD_JPY", "M5", 1)

    assert isinstance(adapter, MarketDataPort)
    assert quote.mid == 150.11
    assert quote.spread == pytest.approx(0.02)
    assert quote.tradeable is True
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


@pytest.mark.contract
def test_execution_adapter_can_require_client_extensions_for_isolated_acceptance():
    client = _Client()
    adapter = OandaExecutionAdapter(
        client,
        include_client_extensions=True,
    )
    request = BrokerOrderRequest(
        "USD_JPY",
        1,
        OrderType.LIMIT,
        150.0,
        150.2,
        149.8,
        "ogm-practice-reference",
    )

    adapter.submit(request)

    assert isinstance(client.endpoints[-1], OrderCreate)
    assert client.endpoints[-1].data["order"]["clientExtensions"]["id"] == (
        "ogm-practice-reference"
    )


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
def test_execution_adapter_classifies_submit_rejection_transient_and_unknown_errors():
    request = BrokerOrderRequest(
        "USD_JPY",
        1,
        OrderType.MARKET,
        150.0,
        150.2,
        149.8,
    )
    rejected = OandaExecutionAdapter(
        _MutationClient(
            [V20Error(400, '{"errorCode":"ORDER_REJECTED","errorMessage":"Invalid order"}')]
        )
    ).submit(request)
    unknown = OandaExecutionAdapter(
        _MutationClient(
            [V20Error(503, '{"errorCode":"SERVICE_UNAVAILABLE","errorMessage":"Retry later"}')]
        )
    ).submit(request)

    assert (rejected.state, rejected.reason) == (
        OrderSubmissionState.REJECTED,
        "ORDER_REJECTED: Invalid order",
    )
    assert (unknown.state, unknown.reason) == (
        OrderSubmissionState.UNKNOWN,
        "SERVICE_UNAVAILABLE: Retry later",
    )

    with pytest.raises(RuntimeError, match="programming defect"):
        OandaExecutionAdapter(
            _MutationClient([RuntimeError("programming defect")])
        ).submit(request)


@pytest.mark.contract
def test_execution_adapter_marks_transient_mutation_failure_as_unknown():
    adapter = OandaExecutionAdapter(
        _MutationClient(
            [V20Error(503, '{"errorCode":"SERVICE_UNAVAILABLE","errorMessage":"Retry later"}')]
        )
    )

    result = adapter.cancel_order("order-1")

    assert result.state is MutationState.UNKNOWN
    assert result.accepted is False
    assert result.message == "SERVICE_UNAVAILABLE: Retry later"


@pytest.mark.contract
@pytest.mark.parametrize(
    "error",
    [
        TimeoutError("request timed out"),
        V20Error(429, '{"errorCode":"RATE_LIMIT","errorMessage":"Slow down"}'),
    ],
)
def test_execution_adapter_never_blindly_retries_uncertain_submit(error):
    client = _MutationClient([error])
    adapter = OandaExecutionAdapter(client)

    result = adapter.submit(
        BrokerOrderRequest(
            "USD_JPY",
            1,
            OrderType.MARKET,
            150.0,
            150.2,
            149.8,
        )
    )

    assert result.state is OrderSubmissionState.UNKNOWN
    assert result.accepted is False
    with pytest.raises(StopIteration):
        client.request(object())


@pytest.mark.contract
def test_query_adapter_maps_pending_and_open_runtime_state_behind_query_port():
    client = _Client()
    adapter = OandaQueryAdapter(client)

    capabilities = adapter.account_capabilities()
    order = adapter.order("order-1")
    trade = adapter.trade("trade-1")
    pending = adapter.pending_orders()
    opened = adapter.open_positions()

    assert isinstance(adapter, BrokerQueryPort)
    assert capabilities.account_id == "account-1"
    assert capabilities.hedging_enabled is True
    assert capabilities.last_transaction_id == "100"
    assert order is not None and order.order_id == "order-1"
    assert trade is not None and trade.trade_id == "trade-1"
    assert pending[0].direction == -1
    assert opened[0].pair == "EUR_USD"
    assert opened[0].direction == -1
    assert opened[0].target_price == 1.105
    assert opened[0].current_stop_loss == 1.11


@pytest.mark.contract
def test_query_adapter_maps_transactions_since_cursor_for_reconciliation():
    client = _Client()
    adapter = OandaQueryAdapter(client)

    batch = adapter.transactions_since("100")

    assert batch.last_transaction_id == "103"
    assert len(batch.transactions) == 2
    created, filled = batch.transactions
    assert (created.transaction_id, created.kind, created.order_id) == (
        "101",
        "LIMIT_ORDER",
        "101",
    )
    assert created.client_reference == "ogm-reference"
    assert created.occurred_at is not None
    assert created.occurred_at.isoformat() == "2026-01-02T01:00:01+00:00"
    assert (created.pair, created.units, created.price) == (
        "USD_JPY",
        100,
        150.1,
    )
    assert (filled.order_id, filled.trade_id, filled.price) == (
        "101",
        "trade-1",
        150.11,
    )
    assert isinstance(client.endpoints[-1], TransactionsSinceID)


@pytest.mark.contract
def test_query_adapter_preserves_submit_terminal_transaction_correlation():
    class _TerminalTransactionClient:
        account_id = "account-1"

        def request(self, endpoint):
            assert isinstance(endpoint, TransactionsSinceID)
            return {
                "lastTransactionID": "202",
                "transactions": [
                    {
                        "id": "201",
                        "type": "LIMIT_ORDER_REJECT",
                        "instrument": "USD_JPY",
                        "units": "100",
                        "price": "150.1",
                        "clientExtensions": {"id": "ogm-rejected"},
                        "rejectReason": "PRICE_INVALID",
                    },
                    {
                        "id": "202",
                        "type": "ORDER_CANCEL",
                        "orderID": "101",
                        "clientOrderID": "ogm-cancelled",
                        "reason": "CLIENT_REQUEST",
                    },
                ],
            }

    batch = OandaQueryAdapter(_TerminalTransactionClient()).transactions_since(
        "200"
    )

    rejected, cancelled = batch.transactions
    assert (
        rejected.kind,
        rejected.client_reference,
        rejected.pair,
        rejected.units,
        rejected.price,
        rejected.reason,
    ) == (
        "LIMIT_ORDER_REJECT",
        "ogm-rejected",
        "USD_JPY",
        100,
        150.1,
        "PRICE_INVALID",
    )
    assert (
        cancelled.kind,
        cancelled.order_id,
        cancelled.client_reference,
        cancelled.reason,
    ) == (
        "ORDER_CANCEL",
        "101",
        "ogm-cancelled",
        "CLIENT_REQUEST",
    )


@pytest.mark.contract
def test_query_adapter_maps_instrument_trading_rules_for_safe_order_sizing():
    client = _Client()
    rules = OandaQueryAdapter(client).instrument_rules("USD_JPY")

    assert rules.pair == "USD_JPY"
    assert rules.minimum_trade_size == 1
    assert rules.maximum_order_units == 1_000_000
    assert rules.trade_units_precision == 0
    assert isinstance(client.endpoints[-1], AccountInstruments)
