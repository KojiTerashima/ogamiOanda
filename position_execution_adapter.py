"""Execution adapter abstraction for live vs. test trading.

Production code (classPosition) calls real Oanda API endpoints.
Test/backtest code (classPositionForTest) simulates execution locally.

This module defines the ``ExecutionAdapter`` protocol so that the two
strategies can be swapped via dependency injection without modifying the
shared position logic in ``PositionCoreMixin``.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class ExecutionAdapter(Protocol):
    """Strategy interface for order/trade execution.

    Concrete implementations must satisfy this interface.  The protocol is
    marked ``runtime_checkable`` so that ``isinstance`` guards can be used in
    tests or at container-wiring time.
    """

    def execute_order(self, oa, for_api_json: dict) -> dict:
        """Submit a new order and return the raw API response dict."""
        ...

    def cancel_order(self, oa, o_id: int) -> dict:
        """Cancel a pending order by ID and return the raw response dict."""
        ...

    def execute_close_trade(self, oa, t_id: int, units) -> dict:
        """Close (or partially close) an open trade and return the response."""
        ...


class LiveExecutionAdapter:
    """Delegates execution calls to the real Oanda API objects.

    Wiring example (in DependencyContainer or classPosition.__init__)::

        adapter = LiveExecutionAdapter()
        # then pass adapter wherever ExecutionAdapter is expected
    """

    def execute_order(self, oa, for_api_json: dict) -> dict:
        return oa.OrderCreate_dic_exe(for_api_json)

    def cancel_order(self, oa, o_id: int) -> dict:
        return oa.OrderCancel_exe(o_id)

    def execute_close_trade(self, oa, t_id: int, units) -> dict:
        return oa.TradeClose_exe(t_id, units)


class TestExecutionAdapter:
    """Simulates execution locally without calling any external API.

    Records all submitted calls so tests can assert on them.
    """

    def __init__(self) -> None:
        self.submitted_orders: list[dict] = []
        self.cancelled_orders: list[int] = []
        self.closed_trades: list[tuple] = []

    def execute_order(self, oa, for_api_json: dict) -> dict:
        self.submitted_orders.append(for_api_json)
        return {"orderFillTransaction": {"id": "1", "price": "0.0"}}

    def cancel_order(self, oa, o_id: int) -> dict:
        self.cancelled_orders.append(o_id)
        return {"orderCancelTransaction": {"id": str(o_id)}}

    def execute_close_trade(self, oa, t_id: int, units) -> dict:
        self.closed_trades.append((t_id, units))
        return {"orderFillTransaction": {"id": str(t_id), "price": "0.0"}}
