from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from enum import Enum


class EntryAction(str, Enum):
    WAIT = "WAIT"
    SUBMIT = "SUBMIT"
    CANCEL = "CANCEL"


@dataclass(frozen=True)
class EntryConfirmationState:
    registered_at: datetime
    step1_started_at: datetime | None = None
    step2_started_at: datetime | None = None
    step1_over_price: float = 0.0


@dataclass(frozen=True)
class EntryConfirmationDecision:
    action: EntryAction
    state: EntryConfirmationState
    reason: str


@dataclass(frozen=True)
class EntryConfirmationPolicy:
    stop_hold_seconds: float = 30
    stop_immediate_gap: float = 0.05
    limit_reverse_hold_seconds: float = 10
    limit_recover_hold_seconds: float = 20
    watching_timeout_seconds: float = 60

    def decide(
        self,
        order_type: str,
        direction: int,
        target_price: float,
        current_price: float,
        now: datetime,
        order_timeout_min: int,
        state: EntryConfirmationState,
    ) -> EntryConfirmationDecision:
        timeout = self._timeout_decision(now, order_timeout_min, state)
        if timeout is not None:
            return timeout
        if order_type.upper() == "STOP":
            return self._stop_decision(direction, target_price, current_price, now, state)
        if order_type.upper() == "LIMIT":
            return self._limit_decision(direction, target_price, current_price, now, state)
        return EntryConfirmationDecision(EntryAction.WAIT, state, "unsupported_order_type")

    def _timeout_decision(
        self,
        now: datetime,
        order_timeout_min: int,
        state: EntryConfirmationState,
    ) -> EntryConfirmationDecision | None:
        if (now - state.registered_at).total_seconds() <= order_timeout_min * 60:
            return None
        watching_seconds = 0.0 if state.step1_started_at is None else (now - state.step1_started_at).total_seconds()
        if watching_seconds == 0 or watching_seconds > self.watching_timeout_seconds:
            return EntryConfirmationDecision(EntryAction.CANCEL, state, "order_and_watching_timeout")
        return None

    def _stop_decision(
        self,
        direction: int,
        target_price: float,
        current_price: float,
        now: datetime,
        state: EntryConfirmationState,
    ) -> EntryConfirmationDecision:
        crossed = (current_price > target_price) if direction == 1 else (current_price < target_price)
        released = (current_price < target_price) if direction == 1 else (current_price > target_price)
        next_state = state
        if state.step1_started_at is None and crossed:
            next_state = replace(
                state,
                step1_started_at=now,
                step1_over_price=abs(current_price - target_price),
            )
        elif state.step1_started_at is not None and released:
            next_state = replace(state, step1_started_at=None, step1_over_price=0.0)

        if next_state.step1_started_at is None:
            return EntryConfirmationDecision(EntryAction.WAIT, next_state, "waiting_for_cross")
        held_seconds = (now - next_state.step1_started_at).total_seconds()
        if held_seconds >= self.stop_hold_seconds or next_state.step1_over_price >= self.stop_immediate_gap:
            cleared = replace(next_state, step1_started_at=None, step1_over_price=0.0)
            return EntryConfirmationDecision(EntryAction.SUBMIT, cleared, "stop_cross_confirmed")
        return EntryConfirmationDecision(EntryAction.WAIT, next_state, "holding_stop_cross")

    def _limit_decision(
        self,
        direction: int,
        target_price: float,
        current_price: float,
        now: datetime,
        state: EntryConfirmationState,
    ) -> EntryConfirmationDecision:
        reverse_crossed = (current_price < target_price) if direction == 1 else (current_price > target_price)
        recovered = (current_price > target_price) if direction == 1 else (current_price < target_price)
        next_state = state

        if state.step2_started_at is not None:
            if not recovered:
                reset = replace(state, step1_started_at=None, step2_started_at=None, step1_over_price=0.0)
                return EntryConfirmationDecision(EntryAction.WAIT, reset, "limit_recovery_released")
            if (now - state.step2_started_at).total_seconds() >= self.limit_recover_hold_seconds:
                reset = replace(state, step1_started_at=None, step2_started_at=None, step1_over_price=0.0)
                return EntryConfirmationDecision(EntryAction.SUBMIT, reset, "limit_recovery_confirmed")
            return EntryConfirmationDecision(EntryAction.WAIT, state, "holding_limit_recovery")

        if state.step1_started_at is None:
            if reverse_crossed:
                next_state = replace(
                    state,
                    step1_started_at=now,
                    step1_over_price=abs(current_price - target_price),
                )
            return EntryConfirmationDecision(EntryAction.WAIT, next_state, "waiting_for_limit_recovery")

        reverse_seconds = (now - state.step1_started_at).total_seconds()
        if recovered and reverse_seconds >= self.limit_reverse_hold_seconds:
            next_state = replace(state, step2_started_at=now)
        elif recovered:
            next_state = replace(state, step1_started_at=None, step1_over_price=0.0)
        return EntryConfirmationDecision(EntryAction.WAIT, next_state, "waiting_for_limit_recovery")
