from classOandaMarketData import OandaMarketDataService


class _FakeApi:
    def __init__(self, responses):
        self._responses = list(responses)

    def request(self, _ep):
        return self._responses.pop(0)


def test_now_price_success():
    responses = [
        {
            "prices": [
                {
                    "bids": [{"price": "150.123"}],
                    "asks": [{"price": "150.133"}],
                }
            ]
        }
    ]

    service = OandaMarketDataService(
        api=_FakeApi(responses),
        account_id="dummy",
        error_handler=lambda *_: {"error": -1},
    )

    res = service.now_price("USD_JPY")

    assert res["error"] == 0
    assert res["data"]["bid"] == 150.123
    assert res["data"]["ask"] == 150.133
    assert res["data"]["mid"] == 150.128
    assert res["data"]["spread"] == 0.01


def test_instruments_candles_multi_uses_copy_of_params():
    candle = {
        "time": "2026-04-06T00:00:00.000000000Z",
        "complete": True,
        "mid": {"o": "150.0", "c": "150.1", "h": "150.2", "l": "149.9"},
    }
    responses = [
        {"candles": [candle]},
        {"candles": [candle]},
    ]
    params = {"granularity": "M5", "count": 1}

    service = OandaMarketDataService(
        api=_FakeApi(responses),
        account_id="dummy",
        error_handler=lambda *_: {"error": -1},
    )

    res = service.instruments_candles_multi("USD_JPY", params, 2)

    assert res["error"] == 0
    assert "to" not in params
