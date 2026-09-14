"""Stream and reconcile completed offline backtests; optionally compare a repeat."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from pathlib import Path

from ogami_oanda.adapters.repositories.historical_store import HistoricalStore, file_hash
from ogami_oanda.application.services.historical_market import HistoricalMarket
from ogami_oanda.domain.market.history import utc_time

ARTIFACTS = ("orders.csv", "trades.csv", "equity.csv", "gaps.csv", "summary.json")
TOLERANCE = 1e-6


def check(value, message):
    if not value:
        raise ValueError(message)


def close(actual, expected, label):
    check(math.isclose(actual, expected, rel_tol=0, abs_tol=TOLERANCE), f"{label}: {actual} != {expected}")


def rows(directory, name):
    with (directory / name).open(encoding="utf-8", newline="") as stream:
        yield from csv.DictReader(stream)


def verify_result(directory: Path, data_dir: Path | None = None) -> dict:
    run = json.loads((directory / "run.json").read_text())
    summary = json.loads((directory / "summary.json").read_text())
    check(run["status"] == "complete", "run is incomplete")
    pending_orders, pending_closes = set(), {}
    for row in rows(directory, "orders.csv"):
        kind, order, trade = row["event"], row["order_id"], row["trade_id"]
        if kind == "SUBMIT":
            check(order not in pending_orders, "duplicate pending order")
            pending_orders.add(order)
        elif kind in {"FILL", "CANCEL"}:
            check(order in pending_orders, "terminal order without submission")
            pending_orders.remove(order)
        elif kind == "CLOSE_REQUEST":
            pending_closes[trade] = pending_closes.get(trade, 0) + int(row["units"])
        elif kind == "CLOSE":
            pending_closes.pop(trade, None)
        elif kind == "REDUCE" and row["reason"] == "MARKET_CLOSE":
            pending_closes[trade] -= int(row["units"])
            if pending_closes[trade] == 0:
                del pending_closes[trade]
    check(not pending_orders and not pending_closes, "unresolved broker orders or close requests")
    active = {}
    completed = 0
    winners = 0
    gross_profit = gross_loss = 0.0
    monthly = {}

    def profits():
        nonlocal completed, winners, gross_profit, gross_loss
        for row in rows(directory, "trades.csv"):
            trade, units, price = row["trade_id"], int(row["units"]), float(row["price"])
            check(units > 0 and math.isfinite(price), "invalid fill units or price")
            if row["event"] == "FILL":
                check(trade not in active, "duplicate open trade")
                active[trade] = {"price": price, "direction": int(row["direction"]), "units": units, "profit": 0.0}
                close(float(row["realized_pl"]), 0, "entry realized profit")
                continue
            check(row["event"] in {"REDUCE", "CLOSE"} and trade in active, "close without open trade")
            position = active[trade]
            check(units <= position["units"], "close exceeds remaining units")
            pnl = float(row["realized_pl"])
            close(pnl, (price - position["price"]) * position["direction"] * units, "fill profit")
            position["units"] -= units
            position["profit"] += pnl
            month = row["time"][:7]
            monthly[month] = monthly.get(month, 0) + pnl
            if row["event"] == "CLOSE":
                check(position["units"] == 0, "CLOSE left units")
                profit = position["profit"]
                completed += 1
                winners += profit > 0
                gross_profit += max(0, profit)
                gross_loss += max(0, -profit)
                del active[trade]
            else:
                check(position["units"] > 0, "REDUCE exhausted trade")
            yield pnl

    realized = math.fsum(profits())
    check(not active, "remaining positions")
    close(run["initial_balance"] + realized, summary["ending_balance"], "ledger ending balance")
    close(realized, summary["realized_pl"], "summary profit")
    check(completed == summary["trade_count"], "trade count mismatch")
    close(gross_profit, summary["gross_profit"], "gross profit")
    close(gross_loss, summary["gross_loss"], "gross loss")
    for key, expected in (("win_rate", winners / completed if completed else None),
                          ("profit_factor", gross_profit / gross_loss if gross_loss else None)):
        if expected is None:
            check(summary[key] is None, f"undefined {key} must be null")
        else:
            close(summary[key], expected, key)
    check(monthly.keys() == summary["monthly_realized_pl"].keys(), "monthly keys mismatch")
    for month, pnl in monthly.items():
        close(pnl, summary["monthly_realized_pl"][month], "monthly profit")
    count = 0
    peak = run["initial_balance"]
    drawdown = drawdown_pct = 0.0
    previous = None
    last = None
    for row in rows(directory, "equity.csv"):
        at = utc_time(row["time"])
        check(previous is None or at >= previous, "equity timestamps out of order")
        previous = at
        balance, unrealized, equity = (float(row[key]) for key in ("balance", "unrealized_pl", "equity"))
        close(balance + unrealized, equity, "equity identity")
        peak = max(peak, equity)
        drawdown = max(drawdown, peak - equity)
        drawdown_pct = max(drawdown_pct, (peak - equity) / peak * 100)
        last = (balance, unrealized, equity)
        count += 1
    check(count == summary["evaluated_candles"] + 1, "equity row count mismatch")
    check(last is not None, "missing equity")
    for actual, key in zip(last, ("ending_balance", "ending_unrealized_pl", "ending_equity")):
        close(actual, summary[key], key)
    close(last[1], 0, "terminal unrealized profit")
    close(drawdown, summary["max_drawdown"], "drawdown")
    close(drawdown_pct, summary["max_drawdown_pct"], "drawdown percentage")
    gap_count = 0
    gap_seconds = 0.0
    for row in rows(directory, "gaps.csv"):
        seconds = (utc_time(row["to"]) - utc_time(row["from"])).total_seconds()
        check(seconds > 0, "invalid gap")
        close(float(row["seconds"]), seconds, "gap duration")
        gap_count += 1
        gap_seconds += seconds
    check(gap_count == summary["gap_count"], "gap count mismatch")
    close(gap_seconds, summary["gap_seconds"], "total gap duration")
    if data_dir is not None:
        manifest = run["data_manifest"]
        encoded = json.dumps(manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
        check(hashlib.sha256(encoded).hexdigest() == run["data_sha256"], "data fingerprint mismatch")
        store = HistoricalStore(data_dir, run["pair"])
        store.manifest = manifest  # Use this run's preserved daily-file references.
        start, end = utc_time(run["from"]), utc_time(run["to"])
        earliest = min(utc_time(interval["from"]) for interval in manifest["intervals"])
        store.validate(earliest, end)
        market = HistoricalMarket(run["pair"], run["requirements"])
        warmup = evaluated = 0
        for candle in store.read(earliest, end):
            if candle.time < start:
                market.advance(candle)
                warmup += 1
            else:
                evaluated += 1
        check(market.ready, "warmup is insufficient")
        check(warmup == summary["warmup_candles"] and evaluated == summary["evaluated_candles"],
              "saved candle count differs from processed count")
    return {"status": "passed", "output_dir": str(directory), "equity_rows": count,
            "trade_count": completed, "realized_pl": realized, "gap_count": gap_count, "gap_seconds": gap_seconds,
            "pending_orders": 0, "remaining_positions": 0, "unresolved_close_requests": 0,
            "portfolio_reconciliation": "enforced by complete run status", "absolute_tolerance": TOLERANCE,
            "artifact_sha256": {name: file_hash(directory / name) for name in ARTIFACTS}}


def compare_results(first: Path, repeat: Path) -> dict:
    for name in ARTIFACTS:
        with (first / name).open("rb") as left, (repeat / name).open("rb") as right:
            while True:
                a, b = left.read(1024 * 1024), right.read(1024 * 1024)
                check(a == b, f"repeat differs: {name}")
                if not a:
                    break
    # Current run metadata contains no elapsed time or output directory.
    # Comparing it also checks code/config/data/environment and terminal state.
    original = json.loads((first / "run.json").read_text())
    repeated = json.loads((repeat / "run.json").read_text())
    check(original == repeated, "repeat provenance or final state differs")
    return {"status": "passed", "byte_identical": list(ARTIFACTS), "run_metadata_identical": True}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--data-dir", type=Path)
    parser.add_argument("--repeat-dir", type=Path)
    args = parser.parse_args(argv)
    result = verify_result(args.output_dir, args.data_dir)
    if args.repeat_dir is not None:
        result["repeat"] = verify_result(args.repeat_dir, args.data_dir)
        result["comparison"] = compare_results(args.output_dir, args.repeat_dir)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
