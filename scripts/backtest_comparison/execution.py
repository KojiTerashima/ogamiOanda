"""Independent order replay and evidence-based execution difference categories."""

from __future__ import annotations

from datetime import datetime, timedelta
import math

import pandas as pd

from ogami_oanda.adapters.backtest.broker import SimulatedBroker
from ogami_oanda.application.services.historical_market import ReplayClock
from ogami_oanda.domain.orders.models import BrokerOrderRequest, OrderType

from .common import differences


def utc(value):
    if value is None:
        return None
    stamp = pd.Timestamp(value)
    stamp = stamp.tz_localize("Asia/Tokyo") if stamp.tzinfo is None else stamp
    return stamp.tz_convert("UTC").isoformat()


def normalize_main(row, candidate):
    entry, close = row.get("entry_price_actual"), row.get("close_price_actual")
    result = {"tp": "tp", "lc": "sl", "time_close": "timeout", "not_closed": "open", "not_filled": "not_filled"}
    return {"filled": row.get("fill_time") is not None, "reason": result.get(row["order_result"], row["order_result"]),
            "fill_bar": utc(row.get("fill_time")), "close_bar": utc(row.get("close_time")),
            "entry_price": entry, "exit_price": close,
            "pnl_quote": ((close-entry)*candidate["direction"]*candidate["units"] if entry is not None and close is not None else None),
            "pips": row.get("actual_res"), "reported_yen": row.get("result_yen"),
            "raw_fill_time": utc(row.get("fill_time")), "raw_close_time": utc(row.get("close_time"))}


def replay_order(pair, decision, candidate, candles, *, amendments=()):
    """Normalized single-order test. Continuous management is tested by run_backtest.

    Mirrors main's verifier boundaries: orders may fill in bars starting at or
    before the pending deadline, the trade timeout close only applies when the
    fill-to-deadline window satisfies main's coverage rule, and positions still
    open at the end of the replay horizon are reported as open, not liquidated.
    """
    decision = pd.Timestamp(decision).to_pydatetime()
    clock = ReplayClock(decision)
    events = []
    active_bar = None

    def observe(event):
        events.append({**event, "bar_start": active_bar.time.isoformat() if active_bar else None})

    broker = SimulatedBroker(pair, clock, initial_balance=1_000_000 if pair == "USD_JPY" else 10_000,
                             slippage_pips=0.5, event_sink=observe)
    broker.submit(BrokerOrderRequest(pair, candidate["direction"]*candidate["units"], OrderType(candidate["order_type"]),
                                    candidate["target_price"], candidate["take_profit_price"], candidate["stop_loss_price"]))
    pending_deadline = decision + timedelta(minutes=candidate["order_timeout_min"])
    timeout_decided = False
    applied = set()
    position_deadline = None
    window_bars = 0
    window_last_end = None
    expected_rows = max(int(candidate["trade_timeout_min"] * 60 / 5), 1)
    for candle in candles:
        active_bar = candle
        for order in broker.pending_orders():
            # main includes bars starting exactly at the deadline in the fill search.
            if candle.time > pending_deadline:
                broker.cancel_order(order.order_id, reason="ORDER_TIMEOUT")
        if position_deadline is not None and candle.time >= position_deadline:
            # main's verifier never inspects bars outside the fill-to-deadline window.
            if not timeout_decided:
                timeout_decided = True
                covered = (window_last_end is not None and window_last_end >= position_deadline
                           and window_bars / expected_rows > 0.5)
                if covered:
                    for trade in broker.open_positions():
                        broker.close_trade(trade.trade_id)
            break
        broker.advance(candle)
        clock.set(candle.end)
        for trade in broker.open_positions():
            if position_deadline is None:
                position_deadline = datetime.fromisoformat(trade.open_time) + timedelta(minutes=candidate["trade_timeout_min"])
            for index, (after_seconds, price) in enumerate(amendments):
                if index not in applied and trade.elapsed_seconds >= after_seconds:
                    broker.amend_protection(trade.trade_id, None, price)
                    applied.add(index)
        if position_deadline is not None and candle.time < position_deadline:
            window_bars += 1
            window_last_end = candle.end
        for trade in broker.open_positions():
            if trade.elapsed_seconds >= candidate["trade_timeout_min"]*60 and not timeout_decided:
                timeout_decided = True
                covered = (window_last_end is not None and window_last_end >= position_deadline
                           and window_bars / expected_rows > 0.5)
                if covered:
                    broker.close_trade(trade.trade_id)
        if not broker.pending_orders() and not broker.open_positions():
            break
    still_open = bool(broker.open_positions())
    broker.finalize()
    fill = next((e for e in events if e["event"] == "FILL"), None)
    close = next((e for e in events if e["event"] == "CLOSE"), None)
    reason = {"TAKE_PROFIT": "tp", "STOP_LOSS": "sl", "MARKET_CLOSE": "timeout"}
    pip = 0.01 if pair == "USD_JPY" else 0.0001
    if still_open:
        # main's verifier reports uncovered or horizon-open trades as open.
        normalized = {"filled": True, "reason": "open",
                      "fill_bar": utc(fill["bar_start"]) if fill else None, "close_bar": None,
                      "entry_price": fill["price"] if fill else None, "exit_price": None,
                      "pnl_quote": None, "pips": None,
                      "raw_fill_time": utc(fill["time"]) if fill else None, "raw_close_time": None}
        return normalized, events
    normalized = {"filled": fill is not None, "reason": reason.get(close["reason"], close["reason"]) if close else "not_filled",
                  "fill_bar": utc(fill["bar_start"]) if fill else None, "close_bar": utc(close["bar_start"]) if close else None,
                  "entry_price": fill["price"] if fill else None, "exit_price": close["price"] if close else None,
                  "pnl_quote": close["realized_pl"] if close else None,
                  "pips": round(close["realized_pl"]/candidate["units"]/pip, 2) if close else None,
                  "raw_fill_time": utc(fill["time"]) if fill else None, "raw_close_time": utc(close["time"]) if close else None}
    return normalized, events


def classify_execution(main, ogami, candidate, events, dataset):
    """Classifications require observable triggering conditions, not only a mismatch."""
    a = {k:v for k,v in main.items() if k not in {"raw_fill_time", "raw_close_time", "reported_yen"}}
    b = {k:v for k,v in ogami.items() if k not in {"raw_fill_time", "raw_close_time", "reported_yen"}}
    delta = differences(a, b, candidate["pair"])
    if not delta:
        if main["raw_fill_time"] != ogami["raw_fill_time"] or main["raw_close_time"] != ogami["raw_close_time"]:
            return delta, ["candle_start_vs_execution_timestamp"]
        return delta, []
    causes = []
    explained = set()
    fields = {d["field"] for d in delta}
    pnl_fields = {"pnl_quote", "pips"}
    pip = .01 if candidate["pair"] == "USD_JPY" else .0001
    direction = candidate["direction"]
    if main["reason"] == ogami["reason"] == "sl" and main["close_bar"] == ogami["close_bar"]:
        if math.isclose(ogami["exit_price"], main["exit_price"]-direction*.5*pip, abs_tol=1e-10):
            causes.append("stop_loss_slippage")
            explained |= {"exit_price"} | pnl_fields
    if main["close_bar"] == ogami["close_bar"] and main["close_bar"] and "exit_price" in fields:
        index = dataset.bounds(main["close_bar"], pd.Timestamp(main["close_bar"])+pd.Timedelta(seconds=5))[0]
        candle = dataset.candle(index, fixed=True)
        opening = candle.bid.open if direction > 0 else candle.ask.open
        if main["reason"] == ogami["reason"] == "sl":
            if ((opening-candidate["stop_loss_price"])*direction < -1e-10
                    and math.isclose(ogami["exit_price"], opening-direction*.5*pip, abs_tol=1e-10)):
                causes.append("stop_loss_opening_gap_and_slippage")
                explained |= {"exit_price"} | pnl_fields
        if main["reason"] == ogami["reason"] == "tp":
            if ((opening-candidate["take_profit_price"])*direction > 1e-10
                    and math.isclose(ogami["exit_price"], opening, abs_tol=1e-10)):
                causes.append("take_profit_opening_improvement")
                explained |= {"exit_price"} | pnl_fields
    fill = next((e for e in events if e["event"] == "FILL"), None)
    if fill and main["fill_bar"] == ogami["fill_bar"] and "entry_price" in fields:
        index = dataset.bounds(fill["bar_start"], pd.Timestamp(fill["bar_start"])+pd.Timedelta(seconds=5))[0]
        candle = dataset.candle(index, fixed=True)
        opening = candle.ask.open if direction>0 else candle.bid.open
        if candidate["order_type"] == "STOP" and (opening-candidate["target_price"])*direction > 1e-10:
            if math.isclose(ogami["entry_price"], opening+direction*.5*pip, abs_tol=1e-10):
                causes.append("stop_opening_gap")
                explained |= {"entry_price"} | pnl_fields
    if fill and main["reason"] == "tp" and main["close_bar"] == main["fill_bar"]:
        if utc(fill["time"]) != utc(fill["bar_start"]) and main["close_bar"] != ogami["close_bar"]:
            causes.append("intrabar_entry_tp_suppressed")
            explained |= {"reason", "close_bar", "exit_price"} | pnl_fields
    if main["reason"] == ogami["reason"] == "timeout" and ({"close_bar", "exit_price"} & fields):
        causes.append("single_order_deadline_and_next_open")
        explained |= {"close_bar", "exit_price"} | pnl_fields
    if fields - explained:
        causes.append("unclassified")
    return delta, causes
