"""Integration-style tests using FakeOanda and TestExecutionAdapter.

These tests validate the position execution flow (order → fill/cancel,
trade → close) end-to-end without calling any real Oanda API.
"""

from position_execution_adapter import TestExecutionAdapter


class FakeOanda:
    """Minimal Oanda-API stub.

    Simulates the responses that classOanda would return so that
    production code can be exercised without network access.
    """

    def OrderCreate_dic_exe(self, payload: dict) -> dict:
        units = payload.get("units", 1000)
        price = payload.get("price", "150.000")
        return {
            "orderFillTransaction": {
                "id": "101",
                "price": price,
                "units": str(units),
                "type": "ORDER_FILL",
                "tradeOpened": {"tradeID": "201"},
            }
        }

    def OrderCancel_exe(self, o_id: int) -> dict:
        return {"orderCancelTransaction": {"id": str(o_id), "type": "ORDER_CANCEL"}}

    def TradeClose_exe(self, t_id: int, units=None) -> dict:
        return {
            "orderFillTransaction": {
                "id": "301",
                "tradesClosed": [{"tradeID": str(t_id), "realizedPL": "5.0"}],
                "type": "ORDER_FILL",
            }
        }

    def TradeDetails_exe(self, t_id: int) -> dict:
        return {
            "trade": {
                "id": str(t_id),
                "currentUnits": "1000",
                "unrealizedPL": "3.0",
                "state": "OPEN",
            }
        }

    def OrderDetails_exe(self, o_id: int) -> dict:
        return {
            "order": {
                "id": str(o_id),
                "state": "PENDING",
                "price": "150.000",
            }
        }


# ---------------------------------------------------------------------------
# FakeOanda self-tests (sanity check)
# ---------------------------------------------------------------------------


def test_fake_oanda_order_create_returns_fill():
    oa = FakeOanda()
    res = oa.OrderCreate_dic_exe({"units": 1000, "price": "150.000"})
    assert "orderFillTransaction" in res
    assert res["orderFillTransaction"]["tradeOpened"]["tradeID"] == "201"


def test_fake_oanda_order_cancel():
    oa = FakeOanda()
    res = oa.OrderCancel_exe(42)
    assert res["orderCancelTransaction"]["id"] == "42"


def test_fake_oanda_trade_close():
    oa = FakeOanda()
    res = oa.TradeClose_exe(201, units=None)
    trades_closed = res["orderFillTransaction"]["tradesClosed"]
    assert trades_closed[0]["tradeID"] == "201"
    assert float(trades_closed[0]["realizedPL"]) == 5.0


def test_fake_oanda_trade_details():
    oa = FakeOanda()
    res = oa.TradeDetails_exe(201)
    assert res["trade"]["state"] == "OPEN"


def test_fake_oanda_order_details():
    oa = FakeOanda()
    res = oa.OrderDetails_exe(10)
    assert res["order"]["state"] == "PENDING"


# ---------------------------------------------------------------------------
# TestExecutionAdapter + FakeOanda integration
# ---------------------------------------------------------------------------


def test_adapter_execute_order_uses_fake_oanda():
    oa = FakeOanda()
    adapter = TestExecutionAdapter()
    payload = {"units": 500, "price": "150.500"}
    result = adapter.execute_order(oa, payload)
    assert adapter.submitted_orders == [payload]
    # stub response contains orderFillTransaction key
    assert "orderFillTransaction" in result


def test_adapter_cancel_order_uses_fake_oanda():
    oa = FakeOanda()
    adapter = TestExecutionAdapter()
    result = adapter.cancel_order(oa, 55)
    assert 55 in adapter.cancelled_orders
    assert "orderCancelTransaction" in result


def test_adapter_close_trade_uses_fake_oanda():
    oa = FakeOanda()
    adapter = TestExecutionAdapter()
    result = adapter.execute_close_trade(oa, 201, units=None)
    assert (201, None) in adapter.closed_trades
    assert "orderFillTransaction" in result


def test_order_then_cancel_sequence():
    oa = FakeOanda()
    adapter = TestExecutionAdapter()

    adapter.execute_order(oa, {"units": 1000})
    adapter.cancel_order(oa, 101)

    assert len(adapter.submitted_orders) == 1
    assert 101 in adapter.cancelled_orders


def test_multiple_order_then_close_sequence():
    oa = FakeOanda()
    adapter = TestExecutionAdapter()

    for i in range(3):
        adapter.execute_order(oa, {"units": 1000 * (i + 1)})

    adapter.execute_close_trade(oa, 201, units=None)

    assert len(adapter.submitted_orders) == 3
    assert len(adapter.closed_trades) == 1


def test_adapter_records_are_independent_per_instance():
    oa = FakeOanda()
    adapter_a = TestExecutionAdapter()
    adapter_b = TestExecutionAdapter()

    adapter_a.execute_order(oa, {"seq": 1})
    adapter_b.execute_order(oa, {"seq": 2})
    adapter_b.execute_order(oa, {"seq": 3})

    assert len(adapter_a.submitted_orders) == 1
    assert len(adapter_b.submitted_orders) == 2


def test_close_with_partial_units():
    oa = FakeOanda()
    adapter = TestExecutionAdapter()
    adapter.execute_close_trade(oa, 201, units=-500)
    assert adapter.closed_trades == [(201, -500)]
