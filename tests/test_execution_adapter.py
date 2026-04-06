"""Tests for ExecutionAdapter protocol and concrete adapters."""

from unittest.mock import MagicMock

from position_execution_adapter import (
    ExecutionAdapter,
    LiveExecutionAdapter,
    TestExecutionAdapter,
)


# ---------------------------------------------------------------------------
# Protocol conformance
# ---------------------------------------------------------------------------


def test_live_adapter_satisfies_protocol():
    assert isinstance(LiveExecutionAdapter(), ExecutionAdapter)


def test_test_adapter_satisfies_protocol():
    assert isinstance(TestExecutionAdapter(), ExecutionAdapter)


# ---------------------------------------------------------------------------
# LiveExecutionAdapter — delegates to oa object
# ---------------------------------------------------------------------------


def test_live_execute_order():
    oa = MagicMock()
    oa.OrderCreate_dic_exe.return_value = {"ok": True}
    adapter = LiveExecutionAdapter()
    result = adapter.execute_order(oa, {"units": 1000})
    oa.OrderCreate_dic_exe.assert_called_once_with({"units": 1000})
    assert result == {"ok": True}


def test_live_cancel_order():
    oa = MagicMock()
    oa.OrderCancel_exe.return_value = {"cancelled": True}
    adapter = LiveExecutionAdapter()
    result = adapter.cancel_order(oa, 42)
    oa.OrderCancel_exe.assert_called_once_with(42)
    assert result == {"cancelled": True}


def test_live_execute_close_trade():
    oa = MagicMock()
    oa.TradeClose_exe.return_value = {"closed": True}
    adapter = LiveExecutionAdapter()
    result = adapter.execute_close_trade(oa, 7, None)
    oa.TradeClose_exe.assert_called_once_with(7, None)
    assert result == {"closed": True}


# ---------------------------------------------------------------------------
# TestExecutionAdapter — records calls, returns stubs
# ---------------------------------------------------------------------------


def test_test_execute_order_records():
    adapter = TestExecutionAdapter()
    payload = {"units": 500, "price": "1.0"}
    result = adapter.execute_order(None, payload)
    assert adapter.submitted_orders == [payload]
    assert "orderFillTransaction" in result


def test_test_cancel_order_records():
    adapter = TestExecutionAdapter()
    adapter.cancel_order(None, 99)
    assert adapter.cancelled_orders == [99]


def test_test_close_trade_records():
    adapter = TestExecutionAdapter()
    adapter.execute_close_trade(None, 3, -500)
    assert adapter.closed_trades == [(3, -500)]


def test_test_adapter_multiple_orders():
    adapter = TestExecutionAdapter()
    for i in range(3):
        adapter.execute_order(None, {"seq": i})
    assert len(adapter.submitted_orders) == 3
