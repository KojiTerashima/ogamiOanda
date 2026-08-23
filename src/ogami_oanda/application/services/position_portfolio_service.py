from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
from ogami_oanda.application.ports.broker import (
    BrokerExecutionPort,
    BrokerQueryPort,
    MutationState,
)
from ogami_oanda.application.ports.position_state import (
    CheckpointLoadStatus,
    PendingBrokerMutation,
    PortfolioAnalyticsState,
    PositionStateCheckpoint,
    PositionStateRepository,
)
from ogami_oanda.application.settings import TradingSettings
from ogami_oanda.application.services.portfolio import ActiveOrder, Portfolio
from ogami_oanda.application.services.position_service import (
    CandleStopLossInput,
    PositionService,
)
from ogami_oanda.domain.market.currency_pair import currency_pair
from ogami_oanda.domain.orders.models import OrderPlan
from ogami_oanda.domain.positions.managed_position import ManagedPosition
from ogami_oanda.domain.positions.models import (
    PositionCommand,
    PositionEvent,
    PositionSnapshot,
    SubmissionPhase,
)
from ogami_oanda.strategy.position_management import (
    HedgePolicy,
    HedgePosition,
    LinkagePolicy,
    LinkedPosition,
)


@dataclass(frozen=True)
class RegistrationResult:
    accepted: tuple[str, ...]
    rejected: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class PortfolioSummary:
    watching: int
    pending: int
    open: int
    closed: int
    commands: tuple[PositionCommand, ...] = ()
    events: tuple[PositionEvent, ...] = ()
    close_events: tuple[PositionEvent, ...] = ()


class PositionStatePersistenceError(RuntimeError):
    pass


class PortfolioStartupState(str, Enum):
    NOT_STARTED = "NOT_STARTED"
    RECONCILING = "RECONCILING"
    READY = "READY"
    QUARANTINED = "QUARANTINED"


@dataclass(frozen=True)
class PortfolioStartupResult:
    state: PortfolioStartupState
    restored: tuple[str, ...] = ()
    reason: str = ""


class PositionPortfolioService:
    def __init__(
        self,
        pair: str,
        position_service: PositionService,
        broker_query: BrokerQueryPort,
        broker_execution: BrokerExecutionPort,
        settings: TradingSettings = TradingSettings(),
        *,
        linkage_policy: LinkagePolicy | None = None,
        hedge_policy: HedgePolicy | None = None,
        state_repository: PositionStateRepository | None = None,
        account_hash: str = "",
        state_writable: bool = True,
    ) -> None:
        self.pair = pair
        self.position_service = position_service
        self.broker_query = broker_query
        self.broker_execution = broker_execution
        self.settings = settings
        self.slots: list[ManagedPosition | None] = [None] * settings.max_positions
        self.linkage_policy = linkage_policy or LinkagePolicy(currency_pair(pair).round_keta)
        self.hedge_policy = hedge_policy or HedgePolicy()
        self.state_repository = state_repository
        self.account_hash = account_hash
        self.state_writable = state_writable
        self.transaction_cursor: str | None = None
        self.pending_mutations: tuple[PendingBrokerMutation, ...] = ()
        self.startup_state = (
            PortfolioStartupState.NOT_STARTED
            if state_repository is not None
            else PortfolioStartupState.READY
        )
        self._checkpoint_slots: list[ManagedPosition | None] | None = None
        self.position_service.set_mutation_hooks(
            self._begin_mutation,
            self._complete_mutation,
        )

    def register_plans(self, plans: list[OrderPlan], submit: bool = True) -> RegistrationResult:
        if self.startup_state is PortfolioStartupState.NOT_STARTED:
            self.restore_and_reconcile()
        if self.startup_state is PortfolioStartupState.QUARANTINED:
            return RegistrationResult(
                (),
                tuple((plan.intent.name, "portfolio_quarantined") for plan in plans),
            )
        if self.pending_mutations:
            return RegistrationResult(
                (),
                tuple((plan.intent.name, "broker_reconciliation") for plan in plans),
            )
        accepted: list[str] = []
        rejected: list[tuple[str, str]] = []
        batch_orders = self._active_orders()
        candidates: list[OrderPlan] = []
        sorted_plans = sorted(
            plans,
            key=lambda plan: abs(currency_pair(self.pair).price_to_pips(plan.target_price - plan.context.current_price)),
        )
        for plan in sorted_plans:
            intent = plan.intent
            if intent.pair != self.pair:
                rejected.append((intent.name, "pair_mismatch"))
                continue
            if self._is_duplicate(plan, batch_orders):
                rejected.append((intent.name, "duplicate"))
                continue
            candidates.append(plan)
            batch_orders.append(
                ActiveOrder(
                    intent.name,
                    intent.direction.value,
                    plan.target_price,
                    intent.metadata.get("source"),
                    intent.metadata.get("line_strategy"),
                )
            )

        overfull_tiers = {
            tier
            for tier in {self._priority_tier(plan.intent.priority) for plan in candidates}
            if sum(self._priority_tier(plan.intent.priority) == tier for plan in candidates) > self._available_slot_count(tier)
        }
        accepted_candidates = []
        for plan in candidates:
            if self._priority_tier(plan.intent.priority) in overfull_tiers:
                rejected.append((plan.intent.name, "tier_full"))
            else:
                accepted_candidates.append(plan)

        for plan in accepted_candidates:
            intent = plan.intent
            if self.startup_state is PortfolioStartupState.QUARANTINED:
                rejected.append((intent.name, "portfolio_quarantined"))
                continue
            if self.pending_mutations:
                rejected.append((intent.name, "broker_reconciliation"))
                continue
            slot_index = self._first_empty_slot(intent.priority)
            if slot_index is None:
                rejected.append((intent.name, "tier_full"))
                continue
            position = self.position_service.prepare(
                ManagedPosition.registered(intent.name, self.pair),
                plan,
            )
            plan_submit = submit and bool(
                intent.metadata.get("order_permission", True),
            )
            if not plan_submit:
                position = position.watching()
                self.slots[slot_index] = position
                self._persist_state()
            else:
                previous = self.slots[slot_index]
                previous_mutations = self.pending_mutations
                self.slots[slot_index] = position
                try:
                    self._persist_state()
                    submitting = position.with_runtime(
                        submission_phase=SubmissionPhase.SUBMITTING,
                    )
                    self.slots[slot_index] = submitting
                    self._begin_mutation(
                        PendingBrokerMutation(
                            "submit_order",
                            intent.name,
                            plan.broker_request.client_reference,
                            prepared_at=self.position_service.clock.now(),
                        )
                    )
                except PositionStatePersistenceError:
                    self.slots[slot_index] = previous
                    self.pending_mutations = previous_mutations
                    raise
                position = self.position_service.submit_prepared(
                    submitting,
                    journal=False,
                )
                self.slots[slot_index] = position
                self._complete_mutation(
                    position.runtime.submission_phase is SubmissionPhase.UNKNOWN
                )
                self._persist_state()
            if position.snapshot.life:
                self.slots[slot_index] = position
                accepted.append(intent.name)
            elif position.runtime.submission_phase is SubmissionPhase.TERMINAL:
                self.startup_state = PortfolioStartupState.QUARANTINED
                rejected.append((intent.name, "terminal_broker_effect"))
            else:
                rejected.append((intent.name, "broker_rejected"))
        return RegistrationResult(tuple(accepted), tuple(rejected))

    def restore_and_reconcile(self) -> PortfolioStartupResult:
        if self.state_repository is None:
            restored = self.restore_open_positions()
            self.startup_state = PortfolioStartupState.READY
            return PortfolioStartupResult(self.startup_state, restored)

        loaded = self.state_repository.load(
            expected_account_hash=self.account_hash,
            expected_pair=self.pair,
        )
        pending = tuple(
            snapshot
            for snapshot in self.broker_query.pending_orders()
            if snapshot.pair == self.pair
        )
        opened = tuple(
            snapshot
            for snapshot in self.broker_query.open_positions()
            if snapshot.pair == self.pair
        )
        if loaded.status is CheckpointLoadStatus.MISSING:
            if pending or opened:
                return self._quarantine("broker positions exist without local checkpoint")
            capabilities = self.broker_query.account_capabilities()
            self.transaction_cursor = capabilities.last_transaction_id
            self.startup_state = PortfolioStartupState.READY
            self._persist_state()
            return PortfolioStartupResult(self.startup_state)
        if loaded.status not in {
            CheckpointLoadStatus.LOADED,
            CheckpointLoadStatus.LOADED_FROM_BACKUP,
        } or loaded.checkpoint is None:
            return self._quarantine(loaded.reason or loaded.status.value)

        checkpoint = loaded.checkpoint
        self.slots = list(checkpoint.slots)
        self.transaction_cursor = checkpoint.transaction_cursor
        self.pending_mutations = checkpoint.pending_mutations
        self.position_service._emitted_event_ids = set(checkpoint.emitted_event_ids)
        reporting = self.position_service.closure_reporting
        history_reported_ids = set(reporting._reported_event_ids)
        reporting._reported_event_ids.update(checkpoint.reported_event_ids)
        if not history_reported_ids:
            self._restore_analytics(checkpoint.analytics)
        if any(
            position is not None
            and position.runtime.submission_phase is SubmissionPhase.TERMINAL
            for position in self.slots
        ):
            return self._quarantine("terminal_broker_effect")

        prepared_positions = [
            position
            for position in self.slots
            if position is not None
            and position.runtime.submission_phase is SubmissionPhase.PREPARED
        ]
        if prepared_positions:
            if (
                loaded.status is CheckpointLoadStatus.LOADED_FROM_BACKUP
                or not self.state_writable
            ):
                return self._quarantine(
                    "prepared order cannot be submitted from untrusted checkpoint"
                )
            persisted_order_ids = {
                position.snapshot.order_id
                for position in self.slots
                if position is not None
                and position.snapshot.order_id is not None
            }
            persisted_trade_ids = {
                position.snapshot.trade_id
                for position in self.slots
                if position is not None
                and position.snapshot.trade_id is not None
            }
            if any(
                item.order_id not in persisted_order_ids for item in pending
            ) or any(item.trade_id not in persisted_trade_ids for item in opened):
                return self._quarantine(
                    "broker state exists before prepared order submission"
                )

        submitted_prepared_names = self._submit_prepared_positions()
        if self.startup_state is PortfolioStartupState.QUARANTINED:
            return PortfolioStartupResult(
                self.startup_state,
                reason="terminal_broker_effect",
            )

        transactions = (
            self.broker_query.transactions_since(self.transaction_cursor)
            if self.transaction_cursor is not None
            else None
        )
        if transactions is not None:
            previous_cursor = self.transaction_cursor
            self._resolve_pending_mutations(
                transactions.transactions,
                pending,
                opened,
            )
            self._promote_filled_pending_positions(
                transactions.transactions,
                opened,
            )
            self.transaction_cursor = (
                previous_cursor
                if self.pending_mutations
                else transactions.last_transaction_id
            )

        persisted_order_ids = {
            position.snapshot.order_id
            for position in self.slots
            if position is not None and position.snapshot.order_id is not None
        }
        persisted_trade_ids = {
            position.snapshot.trade_id
            for position in self.slots
            if position is not None and position.snapshot.trade_id is not None
        }
        orphan_orders = [item for item in pending if item.order_id not in persisted_order_ids]
        orphan_trades = [item for item in opened if item.trade_id not in persisted_trade_ids]
        if orphan_orders or orphan_trades:
            return self._quarantine("broker state could not be matched uniquely")

        opened_by_id = {item.trade_id: item for item in opened if item.trade_id}
        pending_by_id = {item.order_id: item for item in pending if item.order_id}
        pending_submit_names = {
            mutation.position_name
            for mutation in self.pending_mutations
            if mutation.action == "submit_order"
        }
        pending_mutation_names = {
            mutation.position_name
            for mutation in self.pending_mutations
        }
        for index, position in enumerate(self.slots):
            if position is None or not position.snapshot.life:
                continue
            if position.snapshot.name in (
                submitted_prepared_names | pending_submit_names
            ):
                continue
            if position.snapshot.waiting_order:
                continue
            if position.snapshot.trade_id is not None:
                broker_snapshot = opened_by_id.get(position.snapshot.trade_id)
            elif position.snapshot.order_id is not None:
                broker_snapshot = pending_by_id.get(position.snapshot.order_id)
            else:
                broker_snapshot = None
            if broker_snapshot is None:
                if position.snapshot.name in pending_mutation_names:
                    continue
                if self._resolve_stopped_terminal_position(index, position):
                    continue
                return self._quarantine(
                    f"persisted position missing at broker: {position.snapshot.name}"
                )
            self.slots[index] = self.position_service._with_broker_runtime(
                position,
                broker_snapshot,
            )

        self.startup_state = (
            PortfolioStartupState.RECONCILING
            if self.pending_mutations
            else PortfolioStartupState.READY
        )
        self._persist_state()
        return PortfolioStartupResult(
            self.startup_state,
            tuple(
                position.snapshot.name
                for position in self.slots
                if position is not None and position.snapshot.life
            ),
        )

    def _resolve_stopped_terminal_position(
        self,
        index: int,
        position: ManagedPosition,
    ) -> bool:
        if position.snapshot.trade_id is not None:
            broker_snapshot = self.broker_query.trade(position.snapshot.trade_id)
            if (
                broker_snapshot is not None
                and broker_snapshot.trade_state.value == "CLOSED"
            ):
                self._apply_closed_snapshot(index, position, broker_snapshot)
                return True
            return False
        if position.snapshot.order_id is not None:
            broker_snapshot = self.broker_query.order(position.snapshot.order_id)
            if (
                broker_snapshot is not None
                and broker_snapshot.order_state.value in {"CANCELLED", "REJECTED"}
            ):
                self.slots[index] = position.cancelled()
                return True
        return False

    def _apply_closed_snapshot(
        self,
        index: int,
        position: ManagedPosition,
        broker_snapshot: PositionSnapshot,
    ) -> None:
        closed = self.position_service._with_broker_runtime(
            position,
            broker_snapshot,
        ).closed()
        self.slots[index] = closed
        reference_id = broker_snapshot.trade_id or position.snapshot.trade_id
        event = PositionEvent(
            f"trade_closed:{reference_id}",
            "trade_closed",
            closed.snapshot.name,
            closed.snapshot.pair,
            self.position_service.clock.now(),
            {
                "position": closed,
                "broker_snapshot": broker_snapshot,
            },
        )
        events = self.position_service._events_once(event, False)
        if events:
            self.position_service.closure_reporting.report(event)

    def reconcile_pending_mutations(self) -> bool:
        if not self.pending_mutations:
            if self.startup_state is PortfolioStartupState.RECONCILING:
                self.startup_state = PortfolioStartupState.READY
            return True
        if self.transaction_cursor is None:
            return False
        transactions = self.broker_query.transactions_since(
            self.transaction_cursor
        )
        previous_cursor = self.transaction_cursor
        pending = tuple(
            snapshot
            for snapshot in self.broker_query.pending_orders()
            if snapshot.pair == self.pair
        )
        opened = tuple(
            snapshot
            for snapshot in self.broker_query.open_positions()
            if snapshot.pair == self.pair
        )
        self._resolve_pending_mutations(
            transactions.transactions,
            pending,
            opened,
        )
        self._promote_filled_pending_positions(
            transactions.transactions,
            opened,
        )
        if self.pending_mutations:
            self.transaction_cursor = previous_cursor
            self.startup_state = PortfolioStartupState.RECONCILING
            self._persist_state()
            return False
        self.transaction_cursor = transactions.last_transaction_id
        self.startup_state = PortfolioStartupState.READY
        self._persist_state()
        return True

    def _promote_filled_pending_positions(self, transactions, opened) -> None:
        opened_by_id = {item.trade_id: item for item in opened if item.trade_id}
        fills_by_order = {
            item.order_id: item
            for item in transactions
            if item.kind == "ORDER_FILL"
            and item.order_id is not None
            and item.trade_id is not None
            and item.trade_id in opened_by_id
        }
        for index, position in enumerate(self.slots):
            if (
                position is None
                or position.snapshot.trade_id is not None
                or position.snapshot.order_id not in fills_by_order
            ):
                continue
            fill = fills_by_order[position.snapshot.order_id]
            opened_position = position.filled(
                fill.trade_id,
                self.position_service.clock.now(),
                order_id=fill.order_id,
                fill_price=fill.price,
            )
            self.slots[index] = self.position_service._with_broker_runtime(
                opened_position,
                opened_by_id[fill.trade_id],
            )

    def _resolve_pending_mutations(self, transactions, pending, opened) -> None:
        if not self.pending_mutations:
            return
        pending_by_id = {item.order_id: item for item in pending if item.order_id}
        opened_by_id = {item.trade_id: item for item in opened if item.trade_id}
        remaining = []
        for mutation in self.pending_mutations:
            if mutation.action != "submit_order":
                if not self._resolve_non_submit_mutation(
                    mutation,
                    pending_by_id,
                    opened_by_id,
                    transactions,
                ):
                    remaining.append(mutation)
                continue
            matches = [
                (index, position)
                for index, position in enumerate(self.slots)
                if position is not None
                and position.runtime.order_plan is not None
                and mutation.client_reference
                and position.runtime.order_plan.broker_request.client_reference
                == mutation.client_reference
            ]
            if len(matches) != 1:
                remaining.append(mutation)
                continue
            index, position = matches[0]
            plan = position.runtime.order_plan
            if plan is None:
                remaining.append(mutation)
                continue
            request = plan.broker_request
            pair = currency_pair(request.instrument)
            expected_kind = f"{request.order_type.value}_ORDER"
            rejected_kind = f"{expected_kind}_REJECT"
            correlated = [
                item
                for item in transactions
                if mutation.client_reference
                and item.client_reference == mutation.client_reference
            ]
            created = [item for item in correlated if item.kind == expected_kind]
            rejected = [item for item in correlated if item.kind == rejected_kind]
            if not created and not rejected:
                request_matches = [
                    item
                    for item in transactions
                    if item.kind in {expected_kind, rejected_kind}
                    and not item.client_reference
                    and self._within_submission_window(
                        item.occurred_at,
                        mutation.prepared_at or position.runtime.registered_at,
                    )
                    and item.pair == request.instrument
                    and item.units == request.units
                    and (
                        request.order_type.value == "MARKET"
                        or (
                            item.price is not None
                            and pair.round_price(item.price)
                            == pair.round_price(request.price)
                        )
                    )
                ]
                created = [
                    item for item in request_matches if item.kind == expected_kind
                ]
                rejected = [
                    item for item in request_matches if item.kind == rejected_kind
                ]
            if len(rejected) == 1 and not created:
                rejection = rejected[0]
                self.slots[index] = position.rejected(
                    rejection.reason or rejection.kind,
                )
                continue
            if rejected or len(created) != 1:
                remaining.append(mutation)
                continue
            order_ids = {item.order_id for item in created if item.order_id}
            fills = [
                item
                for item in transactions
                if item.kind == "ORDER_FILL"
                and item.order_id in order_ids
                and item.trade_id is not None
            ]
            if not fills:
                pending_matches = [
                    pending_by_id[order_id]
                    for order_id in order_ids
                    if order_id in pending_by_id
                ]
                if len(pending_matches) == 1:
                    pending_snapshot = pending_matches[0]
                    self.slots[index] = self.position_service._with_broker_runtime(
                        position.pending(str(pending_snapshot.order_id)),
                        pending_snapshot,
                    )
                    continue
                cancellations = [
                    item
                    for item in transactions
                    if item.kind == "ORDER_CANCEL"
                    and (
                        item.order_id in order_ids
                        or (
                            mutation.client_reference
                            and item.client_reference == mutation.client_reference
                        )
                    )
                ]
                if len(cancellations) == 1:
                    cancellation = cancellations[0]
                    self.slots[index] = position.cancelled().with_runtime(
                        submission_reason=cancellation.reason or cancellation.kind,
                    )
                    continue
                remaining.append(mutation)
                continue
            if len(fills) != 1:
                remaining.append(mutation)
                continue
            fill = fills[0]
            if fill.trade_id not in opened_by_id:
                remaining.append(mutation)
                continue
            resolved = position.filled(
                fill.trade_id,
                self.position_service.clock.now(),
                order_id=fill.order_id,
                fill_price=fill.price,
            )
            self.slots[index] = self.position_service._with_broker_runtime(
                resolved,
                opened_by_id[fill.trade_id],
            )
        self.pending_mutations = tuple(remaining)

    def _submit_prepared_positions(self) -> set[str]:
        submitted_names: set[str] = set()
        for index, position in enumerate(self.slots):
            if (
                position is None
                or position.runtime.submission_phase is not SubmissionPhase.PREPARED
                or position.runtime.order_plan is None
            ):
                continue
            plan = position.runtime.order_plan
            submitting = position.with_runtime(
                submission_phase=SubmissionPhase.SUBMITTING,
            )
            self.slots[index] = submitting
            self._begin_mutation(
                PendingBrokerMutation(
                    "submit_order",
                    position.snapshot.name,
                    plan.broker_request.client_reference,
                    prepared_at=(
                        position.runtime.registered_at
                        or self.position_service.clock.now()
                    ),
                )
            )
            submitted = self.position_service.submit_prepared(
                submitting,
                journal=False,
            )
            self.slots[index] = submitted
            submitted_names.add(position.snapshot.name)
            self._complete_mutation(
                submitted.runtime.submission_phase is SubmissionPhase.UNKNOWN
            )
            if submitted.runtime.submission_phase is SubmissionPhase.TERMINAL:
                self.startup_state = PortfolioStartupState.QUARANTINED
                self._persist_state()
                return submitted_names
            self._persist_state()
            if self.pending_mutations:
                return submitted_names
        return submitted_names

    @staticmethod
    def _within_submission_window(occurred_at, prepared_at) -> bool:
        if occurred_at is None:
            return False
        if prepared_at is None:
            return False
        if (occurred_at.tzinfo is None) is not (prepared_at.tzinfo is None):
            return False
        elapsed = (occurred_at - prepared_at).total_seconds()
        return -30 <= elapsed <= 300

    def _resolve_non_submit_mutation(
        self,
        mutation: PendingBrokerMutation,
        pending_by_id: dict[str, PositionSnapshot],
        opened_by_id: dict[str, PositionSnapshot],
        transactions,
    ) -> bool:
        reference_id = mutation.broker_reference_id
        if mutation.action == "cancel_order":
            if reference_id is None or reference_id in pending_by_id:
                return False
            broker_snapshot = self.broker_query.order(reference_id)
            matches = [
                (index, position)
                for index, position in enumerate(self.slots)
                if position is not None
                and position.snapshot.order_id == reference_id
            ]
            fills = [
                item
                for item in transactions
                if item.kind == "ORDER_FILL"
                and item.order_id == reference_id
                and item.trade_id in opened_by_id
            ]
            trade_id = (
                broker_snapshot.trade_id
                if broker_snapshot is not None
                and broker_snapshot.trade_id in opened_by_id
                else fills[0].trade_id
                if len(fills) == 1
                else None
            )
            if trade_id is not None:
                if len(matches) != 1:
                    return False
                index, position = matches[0]
                fill = fills[0] if len(fills) == 1 else None
                opened_position = position.filled(
                    trade_id,
                    self.position_service.clock.now(),
                    order_id=reference_id,
                    fill_price=fill.price if fill is not None else None,
                )
                self.slots[index] = self.position_service._with_broker_runtime(
                    opened_position,
                    opened_by_id[trade_id],
                )
                return True
            if broker_snapshot is None or broker_snapshot.order_state.value not in {
                "CANCELLED",
                "REJECTED",
            }:
                return False
            if len(matches) > 1:
                return False
            if matches:
                index, position = matches[0]
                self.slots[index] = position.cancelled()
            return True
        matches = [
            (index, position)
            for index, position in enumerate(self.slots)
            if position is not None
            and position.snapshot.trade_id == reference_id
        ]
        if len(matches) != 1:
            return False
        index, position = matches[0]
        if mutation.action == "close_trade":
            broker_snapshot = (
                self.broker_query.trade(reference_id)
                if reference_id is not None
                else None
            )
            if broker_snapshot is None or broker_snapshot.trade_state.value != "CLOSED":
                return False
            self._apply_closed_snapshot(index, position, broker_snapshot)
            return True
        if mutation.action == "amend_stop_loss":
            broker_snapshot = opened_by_id.get(reference_id)
            if (
                broker_snapshot is None
                or mutation.stop_loss_price is None
                or broker_snapshot.current_stop_loss is None
                or currency_pair(self.pair).round_price(
                    broker_snapshot.current_stop_loss
                )
                != currency_pair(self.pair).round_price(mutation.stop_loss_price)
            ):
                return False
            changes: dict[str, object] = {
                "current_stop_loss": mutation.stop_loss_price,
            }
            if mutation.applied_lc_change_index is not None:
                changes["applied_lc_change_index"] = mutation.applied_lc_change_index
            if mutation.candle_stop_loss_done is not None:
                changes["candle_stop_loss_done"] = mutation.candle_stop_loss_done
            self.slots[index] = self.position_service._with_broker_runtime(
                position.with_runtime(**changes),
                broker_snapshot,
            )
            return True
        return False

    def _restore_analytics(self, state: PortfolioAnalyticsState) -> None:
        analytics = self.position_service.closure_reporting.analytics
        for name in (
            "total_yen",
            "total_yen_max",
            "total_yen_min",
            "total_price_diff",
            "total_price_diff_max",
            "total_price_diff_min",
            "total_pips",
            "total_pips_max",
            "total_pips_min",
            "plus_yen_position_num",
            "minus_yen_position_num",
            "lc_change_num",
            "before_latest_price_diff",
            "before_latest_pl_pips",
            "before_latest_plu",
            "before_latest_name",
            "result_row",
        ):
            setattr(analytics, name, getattr(state, name))
        analytics.history_plus_minus = list(state.history_plus_minus)
        analytics.history_names = list(state.history_names)
        analytics.history_name_plus_minus = [
            dict(item) for item in state.history_name_plus_minus
        ]
        analytics.result_dic_arr = [dict(item) for item in state.result_dic_arr]

    def _quarantine(self, reason: str) -> PortfolioStartupResult:
        self.startup_state = PortfolioStartupState.QUARANTINED
        return PortfolioStartupResult(self.startup_state, reason=reason)

    def _begin_mutation(self, mutation: PendingBrokerMutation) -> None:
        if self.startup_state is PortfolioStartupState.QUARANTINED:
            raise PositionStatePersistenceError(
                "quarantined portfolio cannot execute broker mutations"
            )
        if not self.state_writable:
            raise PositionStatePersistenceError(
                "read-only portfolio cannot execute broker mutations"
            )
        if self.pending_mutations:
            raise PositionStatePersistenceError(
                "cannot start a broker mutation while another outcome is unresolved"
            )
        if self.transaction_cursor is None:
            capabilities = self.broker_query.account_capabilities()
            if capabilities.last_transaction_id is not None:
                self.transaction_cursor = capabilities.last_transaction_id
            if self.transaction_cursor is None:
                raise PositionStatePersistenceError(
                    "broker mutation requires a transaction cursor"
                )
        self.pending_mutations = (mutation,)
        self._persist_state()

    def _complete_mutation(self, unknown: bool) -> None:
        if not unknown:
            self.pending_mutations = ()

    def _persist_state(self) -> None:
        if self.state_repository is None or not self.state_writable:
            return
        try:
            self.state_repository.save(self._checkpoint())
        except Exception as error:
            raise PositionStatePersistenceError(str(error)) from error

    def _checkpoint(self) -> PositionStateCheckpoint:
        reporting = self.position_service.closure_reporting
        analytics = reporting.analytics
        analytics_state = PortfolioAnalyticsState(
            total_yen=analytics.total_yen,
            total_yen_max=analytics.total_yen_max,
            total_yen_min=analytics.total_yen_min,
            total_price_diff=analytics.total_price_diff,
            total_price_diff_max=analytics.total_price_diff_max,
            total_price_diff_min=analytics.total_price_diff_min,
            total_pips=analytics.total_pips,
            total_pips_max=analytics.total_pips_max,
            total_pips_min=analytics.total_pips_min,
            plus_yen_position_num=analytics.plus_yen_position_num,
            minus_yen_position_num=analytics.minus_yen_position_num,
            lc_change_num=analytics.lc_change_num,
            before_latest_price_diff=analytics.before_latest_price_diff,
            before_latest_pl_pips=analytics.before_latest_pl_pips,
            before_latest_plu=analytics.before_latest_plu,
            before_latest_name=analytics.before_latest_name,
            history_plus_minus=tuple(analytics.history_plus_minus),
            history_names=tuple(analytics.history_names),
            history_name_plus_minus=tuple(analytics.history_name_plus_minus),
            result_dic_arr=tuple(analytics.result_dic_arr),
            result_row=analytics.result_row,
        )
        return PositionStateCheckpoint(
            account_hash=self.account_hash,
            pair=self.pair,
            slots=tuple(self._checkpoint_slots or self.slots),
            transaction_cursor=self.transaction_cursor,
            pending_mutations=self.pending_mutations,
            emitted_event_ids=frozenset(self.position_service._emitted_event_ids),
            reported_event_ids=frozenset(reporting._reported_event_ids),
            analytics=analytics_state,
        )

    def sync_all(
        self,
        *,
        current_price: float | None = None,
        candle_stop_loss: CandleStopLossInput | None = None,
        dry_run: bool = False,
    ) -> PortfolioSummary:
        if self.startup_state is PortfolioStartupState.NOT_STARTED:
            self.restore_and_reconcile()
        if self.startup_state is PortfolioStartupState.QUARANTINED:
            return self.summary()
        if self.pending_mutations and not self.reconcile_pending_mutations():
            return self.summary()
        working_slots = list(self.slots)
        self._checkpoint_slots = working_slots
        commands: list[PositionCommand] = []
        events: list[PositionEvent] = []
        try:
            for index, position in enumerate(self.slots):
                if position is not None and position.snapshot.life:
                    result = self.position_service.sync_result(
                        position,
                        current_price=current_price,
                        candle_stop_loss=candle_stop_loss,
                        dry_run=dry_run,
                    )
                    working_slots[index] = result.position
                    commands.extend(result.commands)
                    events.extend(result.events)
                    if (
                        result.position.runtime.submission_phase
                        is SubmissionPhase.TERMINAL
                    ):
                        self.startup_state = PortfolioStartupState.QUARANTINED
                        break
                    if self.pending_mutations:
                        break

            if (
                not self.pending_mutations
                and self.startup_state is not PortfolioStartupState.QUARANTINED
            ):
                linkage_commands, linkage_events = self._apply_linkage(
                    working_slots,
                    tuple(events),
                    dry_run,
                )
                commands.extend(linkage_commands)
                events.extend(linkage_events)
                if not self.pending_mutations:
                    commands.extend(self._apply_hedge(working_slots, dry_run))
            if not dry_run:
                self.slots = working_slots
                self._persist_state()
            summary = self.summary()
            event_tuple = tuple(events)
            return replace(
                summary,
                commands=tuple(commands),
                events=event_tuple,
                close_events=tuple(event for event in event_tuple if event.kind == "trade_closed"),
            )
        finally:
            self._checkpoint_slots = None

    def restore_open_positions(self) -> tuple[str, ...]:
        restored: list[str] = []
        for snapshot in self.broker_query.open_positions():
            if snapshot.pair != self.pair or not snapshot.life:
                continue
            index = self._first_empty_global_slot()
            if index is None:
                break
            self.slots[index] = ManagedPosition.restored(snapshot)
            restored.append(snapshot.name)
        return tuple(restored)

    def cancel_pending_on_start(self, enabled: bool) -> tuple[str, ...]:
        if not enabled or self.startup_state is not PortfolioStartupState.READY:
            return ()
        cancelled = []
        for snapshot in self.broker_query.pending_orders():
            if snapshot.pair == self.pair and snapshot.order_id is not None:
                result = self._execute_mutation(
                    PendingBrokerMutation(
                        "cancel_order",
                        snapshot.name,
                        broker_reference_id=snapshot.order_id,
                        reason="startup_cancel",
                    ),
                    lambda: self.broker_execution.cancel_order(snapshot.order_id),
                )
                if result.accepted:
                    cancelled.append(snapshot.order_id)
                if self.pending_mutations:
                    break
        return tuple(cancelled)

    def summary(self) -> PortfolioSummary:
        positions = [slot.snapshot for slot in self.slots if slot is not None]
        return PortfolioSummary(
            watching=sum(snapshot.waiting_order for snapshot in positions),
            pending=sum(snapshot.order_state.value == "PENDING" for snapshot in positions),
            open=sum(snapshot.trade_state.value == "OPEN" for snapshot in positions),
            closed=sum(not snapshot.life for snapshot in positions),
        )

    def _active_orders(self) -> list[ActiveOrder]:
        return [
            ActiveOrder(
                slot.snapshot.name,
                slot.runtime.direction,
                slot.runtime.target_price,
                slot.runtime.source,
                slot.runtime.line_strategy,
            )
            for slot in self.slots
            if slot is not None and slot.snapshot.life and slot.runtime.direction in {-1, 1}
        ]

    def _is_duplicate(self, plan: OrderPlan, orders: list[ActiveOrder]) -> bool:
        pair = currency_pair(self.pair)
        source = plan.intent.metadata.get("source")
        line_strategy = plan.intent.metadata.get("line_strategy")
        return Portfolio(pair, tuple(orders)).has_similar_active_order(
            plan.intent.direction.value,
            plan.target_price,
            source=source,
            line_strategy=line_strategy,
        )

    def _first_empty_slot(self, priority: int) -> int | None:
        slot_range = self._slot_range(self._priority_tier(priority))
        return next((index for index in slot_range if self.slots[index] is None or not self.slots[index].snapshot.life), None)

    def _first_empty_global_slot(self) -> int | None:
        return next(
            (index for index, slot in enumerate(self.slots) if slot is None or not slot.snapshot.life),
            None,
        )

    def _priority_tier(self, priority: int) -> str:
        if priority >= self.settings.high_priority_threshold:
            return "high"
        if priority >= self.settings.mid_priority_threshold:
            return "mid"
        return "normal"

    def _slot_range(self, tier: str) -> range:
        if tier == "high":
            return range(self.settings.normal_slot_count + self.settings.mid_slot_count, self.settings.max_positions)
        if tier == "mid":
            return range(self.settings.normal_slot_count, self.settings.normal_slot_count + self.settings.mid_slot_count)
        return range(self.settings.normal_slot_count)

    def _available_slot_count(self, tier: str) -> int:
        return sum(
            self.slots[index] is None or not self.slots[index].snapshot.life
            for index in self._slot_range(tier)
        )

    def _apply_linkage(
        self,
        working_slots: list[ManagedPosition | None],
        lifecycle_events: tuple[PositionEvent, ...],
        dry_run: bool,
    ) -> tuple[tuple[PositionCommand, ...], tuple[PositionEvent, ...]]:
        commands: list[PositionCommand] = []
        events: list[PositionEvent] = []
        for event in lifecycle_events:
            main = event.data.get("position")
            if not isinstance(main, ManagedPosition) or main.runtime.linkage_id is None:
                continue
            linked = self._linked_positions(working_slots, main)
            if event.kind == "trade_opened":
                decisions = self.linkage_policy.on_main_filled(linked)
            elif event.kind == "trade_closed":
                broker_snapshot = event.data.get("broker_snapshot")
                if not isinstance(broker_snapshot, PositionSnapshot):
                    continue
                close_price = float(
                    broker_snapshot.average_close_price
                    or broker_snapshot.current_price
                    or main.runtime.target_price
                )
                price_diff = (close_price - main.runtime.target_price) * main.runtime.direction
                decisions = self.linkage_policy.on_main_closed(
                    main_direction=main.runtime.direction,
                    main_price_diff=price_diff,
                    linked_positions=linked,
                )
            else:
                continue
            for decision in decisions:
                command, command_event = self._execute_linkage_decision(
                    working_slots,
                    decision.action,
                    decision.position_id,
                    decision.stop_loss_price,
                    event.kind,
                    dry_run,
                )
                if command is not None:
                    commands.append(command)
                if command_event is not None:
                    events.append(command_event)
                if self.pending_mutations:
                    return tuple(commands), tuple(events)
        return tuple(commands), tuple(events)

    @staticmethod
    def _linked_positions(
        working_slots: list[ManagedPosition | None],
        main: ManagedPosition,
    ) -> list[LinkedPosition]:
        linked = []
        for position in working_slots:
            if (
                position is None
                or position.snapshot.name == main.snapshot.name
                or position.runtime.linkage_id != main.runtime.linkage_id
            ):
                continue
            plan = position.runtime.order_plan
            stop_loss_range = plan.stop_loss_range if plan is not None else 0.0
            linked.append(
                LinkedPosition(
                    position.snapshot.name,
                    position.runtime.direction,
                    position.runtime.target_price,
                    stop_loss_range,
                    float(position.runtime.current_stop_loss or 0),
                    position.snapshot.order_state,
                    position.snapshot.trade_state,
                    position.snapshot.life,
                    position.runtime.linkage_done,
                )
            )
        return linked

    def _execute_linkage_decision(
        self,
        working_slots: list[ManagedPosition | None],
        action: str,
        position_name: str,
        stop_loss_price: float | None,
        trigger: str,
        dry_run: bool,
    ) -> tuple[PositionCommand | None, PositionEvent | None]:
        match = next(
            (
                (index, position)
                for index, position in enumerate(working_slots)
                if position is not None and position.snapshot.name == position_name
            ),
            None,
        )
        if match is None:
            return None, None
        index, position = match
        if action == "cancel_order":
            reference_id = position.snapshot.order_id
        else:
            reference_id = position.snapshot.trade_id
        command = PositionCommand(action, reference_id, f"linkage_{trigger}", stop_loss_price)
        if dry_run or reference_id is None:
            return command, None
        if action == "cancel_order":
            result = self._execute_mutation(
                PendingBrokerMutation(
                    action,
                    position.snapshot.name,
                    broker_reference_id=reference_id,
                    reason=command.reason,
                ),
                lambda: self.broker_execution.cancel_order(reference_id),
                persist_confirmed=False,
            )
            if not result.accepted:
                return command, None
            updated = position.cancelled()
            working_slots[index] = updated
            event = PositionEvent(
                f"order_cancelled:{reference_id}",
                "order_cancelled",
                updated.snapshot.name,
                updated.snapshot.pair,
                self.position_service.clock.now(),
                {"position": updated, "broker_snapshot": updated.snapshot},
            )
            return command, event
        if action == "amend_stop_loss" and stop_loss_price is not None:
            result = self._execute_mutation(
                PendingBrokerMutation(
                    action,
                    position.snapshot.name,
                    broker_reference_id=reference_id,
                    reason=command.reason,
                ),
                lambda: self.broker_execution.amend_protection(
                    reference_id,
                    None,
                    stop_loss_price,
                ),
                persist_confirmed=False,
            )
            if result.accepted:
                working_slots[index] = position.with_runtime(
                    current_stop_loss=stop_loss_price,
                    linkage_done=True,
                )
            return command, None
        return None, None

    def _apply_hedge(
        self,
        working_slots: list[ManagedPosition | None],
        dry_run: bool,
    ) -> tuple[PositionCommand, ...]:
        open_positions = [
            HedgePosition(
                position.snapshot.name,
                position.runtime.direction,
                position.runtime.unrealized_pl,
            )
            for position in working_slots
            if position is not None and position.snapshot.trade_state.value == "OPEN"
        ]
        commands = []
        for decision in self.hedge_policy.close_commands(open_positions):
            match = next(
                (
                    (index, position)
                    for index, position in enumerate(working_slots)
                    if position is not None and position.snapshot.name == decision.position_id
                ),
                None,
            )
            if match is None:
                continue
            index, position = match
            trade_id = position.snapshot.trade_id
            command = PositionCommand("close_trade", trade_id, "hedge_profit")
            commands.append(command)
            if dry_run or trade_id is None:
                continue
            result = self._execute_mutation(
                PendingBrokerMutation(
                    "close_trade",
                    position.snapshot.name,
                    broker_reference_id=trade_id,
                    reason="hedge_profit",
                ),
                lambda: self.broker_execution.close_trade(trade_id),
                persist_confirmed=False,
            )
            if result.accepted:
                working_slots[index] = position.with_runtime(close_requested=True)
            if self.pending_mutations:
                return tuple(commands)
        return tuple(commands)

    def _execute_mutation(
        self,
        mutation,
        execute,
        *,
        persist_confirmed: bool = True,
    ):
        self._begin_mutation(mutation)
        result = execute()
        self._complete_mutation(result.state is MutationState.UNKNOWN)
        if persist_confirmed:
            self._persist_state()
        return result
