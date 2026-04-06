import turn_order_rules as tor


class _Order:
    def __init__(self, payload):
        self.exe_order = payload


class _Module:
    Order = _Order


def test_create_trend_market_order_payload(monkeypatch):
    monkeypatch.setattr(tor, "OCreate", _Module)

    order = tor.create_trend_market_order(
        name="トレンド 砂時計通常",
        latest_price=150.0,
        direction=1,
        tp=0.12,
        lc=0.08,
        lc_change=[{"exe": True}],
        units=1.1,
        priority=11,
        decision_time="2026-04-06 10:00:00",
        candle_analysis_class=object(),
        lc_change_candle_type="H1",
    )

    assert order.exe_order["name"] == "トレンド 砂時計通常"
    assert order.exe_order["type"] == "MARKET"
    assert order.exe_order["direction"] == 1
    assert order.exe_order["tp"] == 0.12
    assert order.exe_order["lc_change_candle_type"] == "H1"
