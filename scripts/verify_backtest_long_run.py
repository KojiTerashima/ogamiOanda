"""Offline synthetic replay benchmark; a new output directory is required."""

import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import resource
import time

from ogami_oanda.adapters.repositories.historical_store import atomic_json
from ogami_oanda.domain.market.history import HistoricalCandle, OHLC
from ogami_oanda.domain.orders.models import Direction, OrderIntent, OrderType
from ogami_oanda.entrypoints.backtest_run import run_backtest
from ogami_oanda.strategy.shared.contracts import StrategyCommand, StrategyCommandAction, StrategyDecision


class VerificationStrategy:
    data_requirements = {"S5": 250, "M1": 250, "M5": 250, "M30": 250, "H1": 250}

    def __init__(self):
        self.ticks = 0

    def dump_state(self):
        return {"ticks": self.ticks}

    def load_state(self, state):
        self.ticks = state.get("ticks", 0)

    def decide(self, input):
        self.ticks += 1
        for granularity, frame in input.candle_frames.items():
            if len(frame) != self.data_requirements[granularity]:
                raise AssertionError("rolling window size changed")
        if self.ticks % 720 == 1:
            return StrategyDecision(intents=(OrderIntent(
                "USD_JPY", Direction.BUY, OrderType.MARKET, 0, False,
                10, False, 10, False, 100, "verification", 1, 60,
                metadata={"source": "verification", "candle_lc_enabled": False},
            ),))
        if self.ticks % 720 == 10:
            return StrategyDecision(commands=(StrategyCommand(
                StrategyCommandAction.REDUCE_EXPOSURE, "verification", "verification-reduce", 40),))
        if self.ticks % 720 == 20:
            return StrategyDecision(commands=(StrategyCommand(
                StrategyCommandAction.CLOSE_ALL, "verification", "verification-close"),))
        return StrategyDecision()


class SyntheticHistory:
    def __init__(self, start, end):
        self.start = start
        self.end = end
        self.started = False

    def __len__(self):
        raise AssertionError("history must not be materialized")

    def __iter__(self):
        if self.started:
            raise AssertionError("replay must consume history exactly once")
        self.started = True
        current = self.start - timedelta(hours=251)
        prices = []
        for index in range(12):
            value = 150 + index * .001
            prices.append((OHLC(value, value, value, value),
                           OHLC(*(value - .005 for _ in range(4))),
                           OHLC(*(value + .005 for _ in range(4)))))
        index = 0
        while current < self.end:
            yield HistoricalCandle(current, *prices[index % len(prices)])
            current += timedelta(seconds=5)
            index += 1


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=int, default=730)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--max-memory-mib", type=float, default=512)
    args = parser.parse_args(argv)
    if args.days <= 0 or args.max_memory_mib <= 0:
        parser.error("days and memory limit must be positive")
    if args.output_dir.exists():
        parser.error("output directory must not exist")
    start = datetime(2024, 1, 2, tzinfo=timezone.utc)
    end = start + timedelta(days=args.days)
    started = time.perf_counter()
    baseline_rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
    samples = []

    def progress(at):
        memory = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
        samples.append({"time": at.isoformat(), "peak_memory_mib": memory})
        print(json.dumps(samples[-1]), flush=True)
        if memory > args.max_memory_mib:
            raise RuntimeError("synthetic replay exceeded memory limit")

    try:
        summary = run_backtest(VerificationStrategy(), "synthetic-verification", "USD_JPY",
                               SyntheticHistory(start, end), start, end, initial_balance=10000,
                               output_dir=args.output_dir, progress=progress,
                               metadata={"synthetic": True})
        if summary["evaluated_candles"] != args.days * 17280:
            raise AssertionError("replay did not consume every S5 candle")
        if abs(summary["ending_balance"] - 10000 - summary["realized_pl"]) > 1e-8:
            raise AssertionError("balance ledger mismatch")
        if summary["ending_unrealized_pl"] != 0 or not summary["trade_count"]:
            raise AssertionError("replay must close all synthetic trades")
    finally:
        if args.output_dir.is_dir():
            atomic_json(args.output_dir / "benchmark.json", {
                "days": args.days, "elapsed_seconds": time.perf_counter() - started,
                "baseline_memory_mib": baseline_rss,
                "peak_memory_mib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024,
                "daily_memory": samples,
            })
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
