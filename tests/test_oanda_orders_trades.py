from classOandaOrders import OandaOrdersService
from classOandaTrades import OandaTradesService


class _FakeApi:
    def __init__(self, responses):
        self._responses = list(responses)

    def request(self, _ep):
        return self._responses.pop(0)


class _FakeNotifier:
    def __init__(self):
        self.calls = []

    def notify(self, *args):
        self.calls.append(args)


def test_orders_pending_exe_adds_time_columns():
    api = _FakeApi(
        [
            {
                "orders": [
                    {
                        "id": "1",
                        "type": "LIMIT",
                        "createTime": "2026-04-06T00:00:00.000000000Z",
                    }
                ]
            }
        ]
    )
    service = OandaOrdersService(
        api=api,
        account_id="dummy",
        notifier=_FakeNotifier(),
        error_handler=lambda *_: {"error": -1},
    )

    res = service.orders_pending_exe()

    assert res["error"] == 0
    assert "order_time_jp" in res["data"].columns
    assert "past_time_sec" in res["data"].columns


def test_trade_close_uses_make_dic_callback():
    close_json = {
        "orderCreateTransaction": {"id": "10", "time": "2026-04-06T00:00:00.000000000Z"},
        "orderFillTransaction": {
            "id": "11",
            "time": "2026-04-06T00:00:00.000000000Z",
            "price": "150.100",
            "units": "1",
            "reason": "MARKET_ORDER",
            "pl": "0",
            "instrument": "USD_JPY",
            "type": "ORDER_FILL",
            "tradeOpened": {"tradeID": "1"},
        },
    }
    api = _FakeApi([close_json])
    marker = {"ok": True}

    service = OandaTradesService(
        api=api,
        account_id="dummy",
        error_handler=lambda *_: {"error": -1},
        make_dic_func=lambda _: marker,
    )

    res = service.trade_close_exe("1", None)

    assert res["error"] == 0
    assert res["data"] is marker
