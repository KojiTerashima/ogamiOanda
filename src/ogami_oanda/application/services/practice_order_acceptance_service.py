from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Callable
from uuid import uuid4

from ogami_oanda.application.ports.broker import (
    BrokerExecutionPort,
    BrokerQueryPort,
    MutationState,
    OrderSubmissionState,
)
from ogami_oanda.application.ports.market_data import MarketDataPort
from ogami_oanda.domain.market.currency_pair import currency_pair
from ogami_oanda.domain.orders.models import (
    BrokerOrderRequest,
    OrderType,
    submission_fingerprint,
)


class PracticeAcceptanceError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        operations: tuple[PracticeAcceptanceOperation, ...] = (),
    ) -> None:
        super().__init__(message)
        self.operations = operations


@dataclass(frozen=True)
class PracticeAcceptanceOperation:
    pair: str
    order_type: OrderType
    order_id: str | None
    trade_id: str | None
    cleaned_up: bool
    reason: str = ""


@dataclass(frozen=True)
class PracticeAcceptanceReport:
    success: bool
    operations: tuple[PracticeAcceptanceOperation, ...]


class PracticeOrderAcceptanceService:
    def __init__(
        self,
        market_data: MarketDataPort,
        broker_execution: BrokerExecutionPort,
        broker_query: BrokerQueryPort,
        *,
        maximum_units: int = 1,
        pending_distance_pips: float = 50.0,
        protection_distance_pips: float = 100.0,
        poll_attempts: int = 10,
        poll_interval_seconds: float = 0.5,
        sleeper: Callable[[float], None] = lambda _seconds: None,
        run_id_factory: Callable[[], str] = lambda: uuid4().hex,
        expected_account_id: str | None = None,
        require_hedging: bool = True,
    ) -> None:
        self.market_data = market_data
        self.broker_execution = broker_execution
        self.broker_query = broker_query
        self.maximum_units = maximum_units
        self.pending_distance_pips = pending_distance_pips
        self.protection_distance_pips = protection_distance_pips
        self.poll_attempts = poll_attempts
        self.poll_interval_seconds = poll_interval_seconds
        self.sleeper = sleeper
        self.run_id_factory = run_id_factory
        self.expected_account_id = expected_account_id
        self.require_hedging = require_hedging

    def run(self, pairs: tuple[str, ...]) -> PracticeAcceptanceReport:
        capabilities = self.broker_query.account_capabilities()
        if (
            self.expected_account_id is not None
            and capabilities.account_id != self.expected_account_id
        ):
            raise PracticeAcceptanceError(
                "broker account does not match confirmed practice account"
            )
        if self.require_hedging and not capabilities.hedging_enabled:
            raise PracticeAcceptanceError(
                "practice acceptance requires hedging-enabled account"
            )
        baseline_orders = self._pending_ids()
        baseline_trades = self._open_trade_ids()
        if baseline_orders or baseline_trades:
            raise PracticeAcceptanceError(
                "practice acceptance requires no existing pending or open positions"
            )

        operations: list[PracticeAcceptanceOperation] = []
        owned_orders: set[str] = set()
        owned_trades: set[str] = set()
        attempted_orders: set[str] = set()
        attempted_trades: set[str] = set()
        unresolved_requests: dict[
            str,
            tuple[BrokerOrderRequest, int],
        ] = {}
        workflow_error: Exception | None = None
        run_id = self.run_id_factory()
        try:
            preflight: list[tuple[str, float, int]] = []
            for pair_name in pairs:
                quote = self.market_data.current_quote(pair_name)
                if not quote.tradeable:
                    raise PracticeAcceptanceError(
                        f"{pair_name} is not tradeable"
                    )
                pair = currency_pair(pair_name)
                if pair.price_to_pips(quote.spread) > pair.spread_limit_pips:
                    raise PracticeAcceptanceError(
                        f"{pair_name} spread exceeds configured safety limit"
                    )
                rules = self.broker_query.instrument_rules(pair_name)
                units = int(rules.minimum_trade_size)
                if units <= 0 or units > self.maximum_units:
                    raise PracticeAcceptanceError(
                        f"{pair_name} minimum units exceed configured safety limit"
                    )
                if units > rules.maximum_order_units:
                    raise PracticeAcceptanceError(
                        f"{pair_name} minimum units exceed broker maximum"
                    )
                preflight.append((pair_name, quote.mid, units))

            for pair_name, current_price, units in preflight:
                for order_type in (OrderType.LIMIT, OrderType.STOP, OrderType.MARKET):
                    request = self._request(
                        pair_name,
                        current_price,
                        units,
                        order_type,
                        run_id,
                    )
                    operation_index = len(operations)
                    operations.append(
                        PracticeAcceptanceOperation(
                            pair_name,
                            order_type,
                            None,
                            None,
                            False,
                        )
                    )
                    unresolved_requests[request.client_reference] = (
                        request,
                        operation_index,
                    )
                    submission = self.broker_execution.submit(request)
                    order_id = submission.order_id
                    trade_id = submission.trade_id
                    if (
                        submission.state is OrderSubmissionState.PENDING
                        and order_id is not None
                    ):
                        owned_orders.add(order_id)
                    if (
                        submission.state is OrderSubmissionState.FILLED
                        and trade_id is not None
                    ):
                        owned_trades.add(trade_id)
                    if submission.state is OrderSubmissionState.UNKNOWN:
                        discovered_orders, discovered_trades = (
                            self._poll_owned_resources(
                                request,
                                baseline_orders,
                                baseline_trades,
                            )
                        )
                        owned_orders.update(discovered_orders)
                        owned_trades.update(discovered_trades)
                        if len(discovered_orders) == 1:
                            order_id = next(iter(discovered_orders))
                        if len(discovered_trades) == 1:
                            trade_id = next(iter(discovered_trades))

                    operations[operation_index] = (
                        PracticeAcceptanceOperation(
                            pair_name,
                            order_type,
                            order_id,
                            trade_id,
                            False,
                            submission.reason,
                        )
                    )

                    if order_type is OrderType.MARKET:
                        if (
                            submission.state is not OrderSubmissionState.FILLED
                            or trade_id is None
                        ):
                            raise PracticeAcceptanceError(
                                f"{pair_name} MARKET did not open a trade: {submission.reason}"
                            )
                        if not self._poll(
                            lambda: (
                                (snapshot := self.broker_query.trade(trade_id))
                                is not None
                                and snapshot.trade_state.value == "OPEN"
                            )
                        ):
                            raise PracticeAcceptanceError(
                                f"{pair_name} MARKET open could not be confirmed"
                            )
                        attempted_trades.add(trade_id)
                        cleaned = self._close_trade(trade_id)
                        if cleaned:
                            owned_trades.discard(trade_id)
                    else:
                        if (
                            submission.state is not OrderSubmissionState.PENDING
                            or order_id is None
                        ):
                            if trade_id is not None:
                                attempted_trades.add(trade_id)
                                cleaned = self._close_trade(trade_id)
                                if cleaned:
                                    owned_trades.discard(trade_id)
                            raise PracticeAcceptanceError(
                                f"{pair_name} {order_type.value} was not pending: {submission.reason}"
                            )
                        if not self._poll(
                            lambda: (
                                (snapshot := self.broker_query.order(order_id))
                                is not None
                                and snapshot.order_state.value == "PENDING"
                            )
                        ):
                            raise PracticeAcceptanceError(
                                f"{pair_name} {order_type.value} pending state could not be confirmed"
                            )
                        attempted_orders.add(order_id)
                        cleaned, filled_trade_id = self._cancel_or_find_trade(
                            order_id
                        )
                        if filled_trade_id is not None:
                            owned_orders.discard(order_id)
                            owned_trades.add(filled_trade_id)
                            trade_id = filled_trade_id
                            attempted_trades.add(filled_trade_id)
                            if self._close_trade(filled_trade_id):
                                owned_trades.discard(filled_trade_id)
                            operations[operation_index] = (
                                PracticeAcceptanceOperation(
                                    pair_name,
                                    order_type,
                                    order_id,
                                    trade_id,
                                    False,
                                    submission.reason,
                                )
                            )
                            raise PracticeAcceptanceError(
                                f"{pair_name} {order_type.value} filled before "
                                "cancellation; workflow stopped"
                            )
                        if cleaned:
                            owned_orders.discard(order_id)
                    operations[operation_index] = (
                        PracticeAcceptanceOperation(
                            pair_name,
                            order_type,
                            order_id,
                            trade_id,
                            cleaned,
                            submission.reason,
                        )
                    )
                    if not cleaned:
                        raise PracticeAcceptanceError(
                            f"cleanup failed for {pair_name} {order_type.value}"
                        )
                    unresolved_requests.pop(request.client_reference, None)
        except Exception as error:
            workflow_error = error
        finally:
            discovery_errors = self._reconcile_attempted_resources(
                unresolved_requests,
                baseline_orders,
                baseline_trades,
                operations,
                owned_orders,
                owned_trades,
            )
            cleanup_errors = self._cleanup_owned(
                owned_orders,
                owned_trades,
                attempted_orders,
                attempted_trades,
            )
            cleanup_errors = discovery_errors + cleanup_errors
            self._refresh_operation_cleanup(
                operations,
                owned_orders,
                owned_trades,
            )

        try:
            final_orders = self._pending_ids()
            final_trades = self._open_trade_ids()
        except Exception as error:
            raise PracticeAcceptanceError(
                str(error),
                operations=tuple(operations),
            ) from error
        residual_orders = final_orders - baseline_orders
        residual_trades = final_trades - baseline_trades
        if cleanup_errors or residual_orders or residual_trades:
            raise PracticeAcceptanceError(
                "practice acceptance cleanup could not be confirmed",
                operations=tuple(operations),
            ) from workflow_error
        if workflow_error is not None:
            raise PracticeAcceptanceError(
                str(workflow_error),
                operations=tuple(operations),
            ) from workflow_error
        return PracticeAcceptanceReport(True, tuple(operations))

    def _request(
        self,
        pair_name: str,
        current_price: float,
        units: int,
        order_type: OrderType,
        run_id: str,
    ) -> BrokerOrderRequest:
        pair = currency_pair(pair_name)
        pending_distance = pair.pips_to_price(self.pending_distance_pips)
        protection_distance = pair.pips_to_price(self.protection_distance_pips)
        if order_type is OrderType.LIMIT:
            target = pair.round_price(current_price - pending_distance)
        elif order_type is OrderType.STOP:
            target = pair.round_price(current_price + pending_distance)
        else:
            target = pair.round_price(current_price)
        take_profit = pair.round_price(target + protection_distance)
        stop_loss = pair.round_price(target - protection_distance)
        name = f"practice-acceptance-{pair_name}-{order_type.value}"
        reference = submission_fingerprint(
            pair=pair_name,
            name=name,
            decision_time=f"practice-acceptance:{run_id}",
            direction=1,
            order_type=order_type,
            target_price=target,
            units=units,
        )
        return BrokerOrderRequest(
            pair_name,
            units,
            order_type,
            target,
            take_profit,
            stop_loss,
            reference,
        )

    def _cancel_order(self, order_id: str) -> bool:
        result = self.broker_execution.cancel_order(order_id)
        if result.state is MutationState.UNKNOWN:
            cleaned, _filled_trade_id = self._poll_order_cleanup(order_id)
            return cleaned
        if not result.accepted:
            return False
        return self._poll(
            lambda: (
                (snapshot := self.broker_query.order(order_id)) is not None
                and snapshot.order_state.value == "CANCELLED"
            )
        )

    def _cancel_or_find_trade(
        self,
        order_id: str,
    ) -> tuple[bool, str | None]:
        if self._cancel_order(order_id):
            return True, None
        return self._order_cleanup_state(order_id)

    def _close_trade(self, trade_id: str) -> bool:
        result = self.broker_execution.close_trade(trade_id)
        if result.state is MutationState.UNKNOWN:
            return self._poll(
                lambda: self._trade_cleanup_confirmed(trade_id)
            )
        if not result.accepted:
            return False
        return self._poll(
            lambda: (
                (snapshot := self.broker_query.trade(trade_id)) is not None
                and snapshot.trade_state.value == "CLOSED"
            )
        )

    def _cleanup_owned(
        self,
        order_ids: set[str],
        trade_ids: set[str],
        attempted_order_ids: set[str],
        attempted_trade_ids: set[str],
    ) -> list[str]:
        errors: list[str] = []
        for order_id in tuple(order_ids):
            try:
                if order_id in attempted_order_ids:
                    cancelled, filled_trade_id = self._order_cleanup_state(
                        order_id
                    )
                else:
                    cancelled, filled_trade_id = self._cancel_or_find_trade(
                        order_id
                    )
                if cancelled:
                    order_ids.discard(order_id)
                elif filled_trade_id is not None:
                    order_ids.discard(order_id)
                    trade_ids.add(filled_trade_id)
                else:
                    errors.append(f"order:{order_id}")
            except Exception:
                errors.append(f"order:{order_id}")
        for trade_id in tuple(trade_ids):
            try:
                cleaned = (
                    self._trade_cleanup_confirmed(trade_id)
                    if trade_id in attempted_trade_ids
                    else self._close_trade(trade_id)
                )
                if cleaned:
                    trade_ids.discard(trade_id)
                else:
                    errors.append(f"trade:{trade_id}")
            except Exception:
                errors.append(f"trade:{trade_id}")
        return errors

    def _pending_ids(self) -> set[str]:
        return {
            snapshot.order_id
            for snapshot in self.broker_query.pending_orders()
            if snapshot.order_id is not None
        }

    def _open_trade_ids(self) -> set[str]:
        return {
            snapshot.trade_id
            for snapshot in self.broker_query.open_positions()
            if snapshot.trade_id is not None
        }

    def _owned_resources(
        self,
        request: BrokerOrderRequest,
        baseline_orders: set[str],
        baseline_trades: set[str],
    ) -> tuple[set[str], set[str]]:
        pending = [
            snapshot
            for snapshot in self.broker_query.pending_orders()
            if snapshot.order_id is not None
            and snapshot.order_id not in baseline_orders
        ]
        opened = [
            snapshot
            for snapshot in self.broker_query.open_positions()
            if snapshot.trade_id is not None
            and snapshot.trade_id not in baseline_trades
        ]

        referenced_orders = {
            snapshot.order_id
            for snapshot in pending
            if snapshot.client_reference == request.client_reference
        }
        referenced_trades = {
            snapshot.trade_id
            for snapshot in opened
            if snapshot.client_reference == request.client_reference
        }
        return referenced_orders, referenced_trades

    def _reconcile_attempted_resources(
        self,
        unresolved_requests: dict[
            str,
            tuple[BrokerOrderRequest, int],
        ],
        baseline_orders: set[str],
        baseline_trades: set[str],
        operations: list[PracticeAcceptanceOperation],
        owned_orders: set[str],
        owned_trades: set[str],
    ) -> list[str]:
        errors: list[str] = []
        for request, operation_index in unresolved_requests.values():
            try:
                order_ids, trade_ids = self._poll_owned_resources(
                    request,
                    baseline_orders,
                    baseline_trades,
                )
            except Exception:
                errors.append(
                    f"reference:{request.client_reference}"
                )
                continue
            operation = operations[operation_index]
            owned_orders.update(order_ids)
            owned_trades.update(trade_ids)
            if trade_ids and operation.order_id is not None:
                owned_orders.discard(operation.order_id)
            operations[operation_index] = replace(
                operation,
                order_id=(
                    next(iter(order_ids))
                    if len(order_ids) == 1
                    else operation.order_id
                ),
                trade_id=(
                    next(iter(trade_ids))
                    if len(trade_ids) == 1
                    else operation.trade_id
                ),
            )
        return errors

    @staticmethod
    def _refresh_operation_cleanup(
        operations: list[PracticeAcceptanceOperation],
        owned_orders: set[str],
        owned_trades: set[str],
    ) -> None:
        for index, operation in enumerate(operations):
            had_resource = (
                operation.order_id is not None
                or operation.trade_id is not None
            )
            if not had_resource:
                continue
            operations[index] = replace(
                operation,
                cleaned_up=(
                    operation.order_id not in owned_orders
                    and operation.trade_id not in owned_trades
                ),
            )

    def _poll_owned_resources(
        self,
        request: BrokerOrderRequest,
        baseline_orders: set[str],
        baseline_trades: set[str],
    ) -> tuple[set[str], set[str]]:
        for attempt in range(self.poll_attempts):
            order_ids, trade_ids = self._owned_resources(
                request,
                baseline_orders,
                baseline_trades,
            )
            if order_ids or trade_ids:
                return order_ids, trade_ids
            if attempt + 1 < self.poll_attempts:
                self.sleeper(self.poll_interval_seconds)
        return set(), set()

    def _poll_order_cleanup(
        self,
        order_id: str,
    ) -> tuple[bool, str | None]:
        for attempt in range(self.poll_attempts):
            cleaned, filled_trade_id = self._order_cleanup_state(order_id)
            if cleaned or filled_trade_id is not None:
                return cleaned, filled_trade_id
            if attempt + 1 < self.poll_attempts:
                self.sleeper(self.poll_interval_seconds)
        return False, None

    def _order_cleanup_state(
        self,
        order_id: str,
    ) -> tuple[bool, str | None]:
        snapshot = self.broker_query.order(order_id)
        if snapshot is None:
            return False, None
        if snapshot.order_state.value in {"CANCELLED", "REJECTED"}:
            return True, None
        if snapshot.trade_id is not None:
            return False, snapshot.trade_id
        return False, None

    def _trade_cleanup_confirmed(self, trade_id: str) -> bool:
        snapshot = self.broker_query.trade(trade_id)
        return (
            snapshot is not None
            and snapshot.trade_state.value == "CLOSED"
        )

    def _poll(self, predicate: Callable[[], bool]) -> bool:
        for attempt in range(self.poll_attempts):
            if predicate():
                return True
            if attempt + 1 < self.poll_attempts:
                self.sleeper(self.poll_interval_seconds)
        return False
