from datetime import datetime, timedelta, timezone

import pytest

from ogami_oanda.domain.market.history import HistoricalCandle, OHLC
from ogami_oanda.domain.orders.models import BrokerOrderRequest, OrderType

START = datetime(2024, 1, 2, tzinfo=timezone.utc)


def bar(i=0, *, open=150, high=150.01, low=149.99, close=150, spread=.02):
    p = (open, high, low, close)
    return HistoricalCandle(START + timedelta(seconds=5 * i), OHLC(*p),
                            OHLC(*(x - spread / 2 for x in p)), OHLC(*(x + spread / 2 for x in p)))


def request(kind=OrderType.MARKET, units=100, price=150, tp=151, sl=149):
    return BrokerOrderRequest("USD_JPY", units, kind, price, tp, sl, "test")


def broker(**kwargs):
    from ogami_oanda.adapters.backtest.broker import SimulatedBroker
    from ogami_oanda.application.services.historical_market import ReplayClock

    return SimulatedBroker("USD_JPY", ReplayClock(START), initial_balance=10000, **kwargs)


@pytest.mark.parametrize("units,price", [(100, 150.01), (-100, 149.99)])
def test_market_waits_for_next_bar_and_uses_correct_quote(units, price):
    b = broker()
    b.advance(bar())
    order = b.submit(request(units=units, tp=151 if units > 0 else 149, sl=149 if units > 0 else 151))
    assert b.order(order.order_id).trade_id is None
    b.advance(bar(1))
    filled = b.order(order.order_id)
    assert filled.target_price == pytest.approx(price)
    assert filled.unrealized_pl == pytest.approx(-2)
    assert b.balance == 10000


@pytest.mark.parametrize("units", [100, -100])
def test_ambiguous_protection_prefers_sl(units):
    b = broker()
    b.submit(request(units=units, tp=151 if units > 0 else 149, sl=149 if units > 0 else 151))
    b.advance(bar())
    b.advance(bar(1, high=152, low=148))
    closed = b.trade("trade-1")
    assert closed.close_reason == "STOP_LOSS"
    assert closed.realized_pl == pytest.approx(-101)
    assert b.balance == pytest.approx(9899)


def test_stop_gap_and_slippage_and_limit_price_improvement():
    b = broker(slippage_pips=1)
    stop = b.submit(request(OrderType.STOP, price=150.2, tp=153))
    b.advance(bar(open=151, high=151.1, low=150.9, close=151))
    assert b.order(stop.order_id).target_price == pytest.approx(151.02)
    limit = b.submit(request(OrderType.LIMIT, price=150.5, tp=153, sl=148))
    b.advance(bar(1))
    assert b.order(limit.order_id).target_price == pytest.approx(150.01)


def test_intrabar_entry_cannot_claim_unknown_same_bar_take_profit():
    b = broker()
    result = b.submit(request(OrderType.LIMIT, price=149.8, tp=150.2, sl=149))
    b.advance(bar(high=150.5, low=149.5))
    assert b.order(result.order_id).trade_state.value == "OPEN"
    b.advance(bar(1, high=150.5))
    assert b.trade("trade-1").close_reason == "TAKE_PROFIT"


def test_partial_close_counts_each_unit_once_and_end_liquidates():
    b = broker()
    b.submit(request(tp=160, sl=140))
    b.advance(bar())
    assert b.close_trade("trade-1", 40).accepted
    assert b.balance == 10000
    b.advance(bar(1, open=151, high=151.01, low=150.99, close=151))
    assert b.trade("trade-1").units == 60
    assert b.balance == pytest.approx(10039.2)
    b.finalize()
    assert b.balance == pytest.approx(10098)
    assert b.trade("trade-1").realized_pl == pytest.approx(98)
    assert b.trade("trade-1").close_reason == "END_OF_TEST"
    assert not b.open_positions()
    assert b.completed_trades == 1


def test_cancel_and_protection_amendment():
    b = broker()
    pending = b.submit(request(OrderType.LIMIT, price=140, sl=130))
    assert b.cancel_order(pending.order_id).accepted
    b.advance(bar())
    assert b.order(pending.order_id).order_state.value == "CANCELLED"
    b.submit(request(tp=160, sl=140))
    b.advance(bar(1))
    assert b.amend_protection("trade-1", None, 149.9).accepted
    b.advance(bar(2, low=149.5))
    assert b.trade("trade-1").average_close_price == 149.9


def test_invalid_orders_and_double_close_are_rejected():
    b = broker()
    assert not b.submit(request(units=0)).accepted
    assert not b.submit(request(tp=float("nan"))).accepted
    b.submit(request())
    b.advance(bar())
    assert not b.close_trade("trade-1", 101).accepted
    assert b.close_trade("trade-1", 80).accepted
    assert not b.close_trade("trade-1", 30).accepted


def test_sell_limit_cannot_fill_below_limit():
    b = broker(slippage_pips=5)
    pending = b.submit(request(OrderType.LIMIT, units=-100, price=150.5, tp=149, sl=152))
    b.advance(bar(open=151, high=151.01, low=150.99, close=151))
    assert b.order(pending.order_id).target_price == pytest.approx(150.99)


@pytest.mark.parametrize("direction", [1, -1])
def test_tp_gap_still_prefers_sl_when_both_levels_are_reached(direction):
    simulation = broker()
    simulation.submit(request(units=100 * direction, tp=150 + direction, sl=150 - direction))
    simulation.advance(bar())
    simulation.advance(bar(1, open=150 + 2 * direction, high=153, low=147))
    assert simulation.trade("trade-1").close_reason == "STOP_LOSS"
    assert simulation.trade("trade-1").average_close_price == 150 - direction


@pytest.mark.parametrize("direction", [1, -1])
def test_stop_and_sl_gaps_apply_adverse_slippage_in_both_directions(direction):
    simulation = broker(slippage_pips=2)
    simulation.submit(request(OrderType.STOP, units=100 * direction, price=150 + direction * .2,
                              tp=150 + 5 * direction, sl=150 - direction))
    entry = 150 + direction
    simulation.advance(bar(open=entry, high=entry + .1, low=entry - .1, close=entry))
    assert simulation.trade("trade-1").target_price == pytest.approx(entry + direction * .03)
    exit_price = 150 - 2 * direction
    simulation.advance(bar(1, open=exit_price, high=exit_price + .1, low=exit_price - .1, close=exit_price))
    assert simulation.trade("trade-1").average_close_price == pytest.approx(exit_price - direction * .03)


@pytest.mark.parametrize("direction", [1, -1])
def test_intrabar_stop_entry_applies_sl_but_never_unknown_tp(direction):
    simulation = broker()
    simulation.submit(request(OrderType.STOP, units=100 * direction, price=150 + direction * .2,
                              tp=150 + direction, sl=150 - direction))
    simulation.advance(bar(high=152, low=148))
    assert simulation.trade("trade-1").close_reason == "STOP_LOSS"


@pytest.mark.parametrize("direction", [1, -1])
def test_finalization_uses_last_quote_close_and_marks_pending_cancellation(direction):
    events = []
    simulation = broker(slippage_pips=2, event_sink=events.append)
    simulation.submit(request(units=100 * direction, tp=150 + 5 * direction, sl=150 - 5 * direction))
    simulation.advance(bar())
    simulation.submit(request(OrderType.LIMIT, price=140, sl=130))
    simulation.finalize()
    assert simulation.trade("trade-1").average_close_price == pytest.approx(150 - direction * .01)
    assert simulation.trade("trade-1").close_reason == "END_OF_TEST"
    assert [event["reason"] for event in events if event["event"] == "CANCEL"] == ["END_OF_TEST"]
    assert not simulation.pending_orders()


def test_finalized_broker_cannot_accept_orders_or_advance():
    simulation = broker()
    simulation.advance(bar())
    simulation.finalize()
    with pytest.raises(RuntimeError, match='finalized'):
        simulation.submit(request())
    with pytest.raises(RuntimeError, match='finalized'):
        simulation.advance(bar(1))
    assert not simulation.pending_orders()
    assert not simulation.open_positions()
