from datetime import datetime, timedelta

import pytest

from ogami_oanda.domain.positions.models import OrderState, PositionSnapshot, TradeState
from ogami_oanda.strategy.position_management import (
    EntryAction,
    EntryConfirmationPolicy,
    EntryConfirmationState,
    ExitPolicy,
    HedgePolicy,
    HedgePosition,
    LinkagePolicy,
    LinkedPosition,
    StopLossPolicy,
)

NOW = datetime(2026, 1, 2, 10, 0, 0)


@pytest.mark.contract
def test_stop_entry_confirmation_requires_hold_and_resets_after_cross_release():
    policy = EntryConfirmationPolicy()
    initial = EntryConfirmationState(registered_at=NOW)

    crossed = policy.decide("STOP", 1, 150.0, 150.01, NOW, 1, initial)
    released = policy.decide("STOP", 1, 150.0, 149.99, NOW + timedelta(seconds=10), 1, crossed.state)
    crossed_again = policy.decide("STOP", 1, 150.0, 150.02, NOW + timedelta(seconds=11), 1, released.state)
    submit = policy.decide("STOP", 1, 150.0, 150.02, NOW + timedelta(seconds=41), 1, crossed_again.state)

    assert crossed.action is EntryAction.WAIT
    assert crossed.state.step1_started_at == NOW
    assert released.state.step1_started_at is None
    assert submit.action is EntryAction.SUBMIT


@pytest.mark.contract
def test_sell_stop_entry_confirmation_submits_at_exact_hold_boundary():
    policy = EntryConfirmationPolicy()
    crossed = policy.decide("STOP", -1, 150.0, 149.99, NOW, 1, EntryConfirmationState(NOW))

    submit = policy.decide("STOP", -1, 150.0, 149.98, NOW + timedelta(seconds=30), 1, crossed.state)

    assert submit.action is EntryAction.SUBMIT


@pytest.mark.contract
def test_watching_timeout_allows_active_cross_for_sixty_seconds_then_cancels():
    policy = EntryConfirmationPolicy()
    state = EntryConfirmationState(registered_at=NOW, step1_started_at=NOW + timedelta(seconds=50))

    within_watch = policy.decide("STOP", 1, 150.0, 150.01, NOW + timedelta(seconds=61), 1, state)
    expired_watch = policy.decide("STOP", 1, 150.0, 150.01, NOW + timedelta(seconds=111), 1, state)
    never_crossed = policy.decide("STOP", 1, 150.0, 149.99, NOW + timedelta(seconds=61), 1, EntryConfirmationState(NOW))

    assert within_watch.action is EntryAction.WAIT
    assert expired_watch.action is EntryAction.CANCEL
    assert never_crossed.action is EntryAction.CANCEL


@pytest.mark.contract
def test_limit_entry_confirmation_requires_reverse_recover_and_twenty_second_hold():
    policy = EntryConfirmationPolicy()
    initial = EntryConfirmationState(registered_at=NOW)

    reverse = policy.decide("LIMIT", 1, 150.0, 149.95, NOW, 5, initial)
    recover = policy.decide("LIMIT", 1, 150.0, 150.05, NOW + timedelta(seconds=11), 5, reverse.state)
    submit = policy.decide("LIMIT", 1, 150.0, 150.06, NOW + timedelta(seconds=31), 5, recover.state)

    assert reverse.state.step1_started_at == NOW
    assert recover.state.step2_started_at == NOW + timedelta(seconds=11)
    assert submit.action is EntryAction.SUBMIT


@pytest.mark.contract
def test_exit_policy_preserves_order_timeout_and_disabled_trade_timeout():
    pending = PositionSnapshot("pending", "USD_JPY", OrderState.PENDING, TradeState.NONE, life=True)
    opened = PositionSnapshot("open", "USD_JPY", OrderState.FILLED, TradeState.OPEN, life=True)
    policy = ExitPolicy(order_timeout_min=1, trade_timeout_min=1)

    assert policy.should_cancel_order(pending, 60) is False
    assert policy.should_cancel_order(pending, 61) is True
    assert policy.should_close(opened, 61) is False
    assert ExitPolicy(1, 1, trade_timeout_enabled=True).should_close(opened, 60) is True


@pytest.mark.contract
def test_stop_loss_policy_selects_first_eligible_unapplied_rule():
    policy = StopLossPolicy()
    rules = [
        {"exe": True, "trigger": 0.03, "ensure": 0.01, "time_after": 0},
        {"exe": True, "trigger": 0.05, "ensure": 0.03, "time_after": 60},
    ]

    first = policy.next_amendment(rules, 150.0, 1, 150.03, 149.9, 120)
    second = policy.next_amendment(rules, 150.0, 1, 150.06, 150.01, 120, applied_indices={0})
    no_regression = policy.next_amendment(rules, 150.0, 1, 150.06, 150.04, 120, applied_indices={0})

    assert first is not None
    assert (first.rule_index, first.stop_loss_price) == (0, pytest.approx(150.01))
    assert second is not None
    assert (second.rule_index, second.stop_loss_price) == (1, pytest.approx(150.03))
    assert no_regression is None


@pytest.mark.contract
def test_candle_stop_loss_uses_previous_candle_and_only_moves_favorably():
    policy = StopLossPolicy()
    peak = {"count": 3, "direction": 1}
    candle = {"low": 150.12, "high": 150.15}

    amended = policy.candle_amendment(150.0, 1, 149.9, 30, peak, candle, datetime(2026, 1, 2, 10, 5, 10))

    assert amended == pytest.approx(150.105)
    assert policy.candle_amendment(150.0, 1, 150.11, 30, peak, candle, datetime(2026, 1, 2, 10, 5, 10)) is None
    assert policy.candle_amendment(150.0, 1, 149.9, 29, peak, candle, datetime(2026, 1, 2, 10, 5, 10)) is None


@pytest.mark.contract
def test_linkage_policy_returns_pending_cancel_and_opposite_loss_lc_commands():
    policy = LinkagePolicy()
    pending = LinkedPosition("pending", -1, 150.0, 0.05, 150.2, OrderState.PENDING, TradeState.NONE, True)
    opened = LinkedPosition("open", -1, 150.0, 0.05, 150.2, OrderState.FILLED, TradeState.OPEN, True)

    cancel = policy.on_main_filled([pending])
    amend = policy.on_main_closed(main_direction=1, main_price_diff=-0.03, linked_positions=[opened])

    assert [(command.action, command.position_id) for command in cancel] == [("cancel_order", "pending")]
    assert [(command.action, command.position_id, command.stop_loss_price) for command in amend] == [
        ("amend_stop_loss", "open", 150.05),
    ]
    assert policy.on_main_filled([]) == ()
    assert policy.on_main_closed(main_direction=1, main_price_diff=0, linked_positions=[opened]) == ()


@pytest.mark.contract
def test_hedge_policy_preserves_legacy_score_gate_no_op():
    policy = HedgePolicy()
    positions = [
        HedgePosition("long", 1, 0.3),
        HedgePosition("short", -1, 0.3),
    ]

    assert policy.close_commands(positions) == ()
