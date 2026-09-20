#!/usr/bin/env python3
"""Compare pinned main resistance breakout calculations and offline executions."""

from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path

from backtest_comparison.common import MONTH_END, PAIRS, PILOT_END, START


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--main-analysis-dir", type=Path, default=Path("../main"))
    parser.add_argument("--data-root", type=Path, default=Path("runtime/history"))
    parser.add_argument("--pairs", choices=PAIRS, nargs="+", default=list(PAIRS))
    parser.add_argument("--from", dest="start", default=START)
    parser.add_argument("--pilot-to", default=PILOT_END)
    parser.add_argument("--max-to", default=MONTH_END)
    parser.add_argument("--workers", type=int, choices=range(1,5), default=3)
    parser.add_argument("--resume", action="store_true")
    monitor = parser.add_mutually_exclusive_group()
    monitor.add_argument("--progress", action="store_true", help="update progress and ETA once from saved artifacts")
    monitor.add_argument("--watch-progress", action="store_true", help="update progress and ETA every 30 seconds")
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--pair", choices=PAIRS, help=argparse.SUPPRESS)
    parser.add_argument("--end", help=argparse.SUPPRESS)
    parser.add_argument("--attempt", default="run", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    root = args.output_dir.resolve()
    if args.progress or args.watch_progress:
        if args.worker or args.resume:
            parser.error("progress observation cannot be combined with worker/resume")
        from backtest_comparison.progress import watch
        watch(root, once=args.progress)
        return
    if args.worker:
        from backtest_comparison.runner import run_pair
        run_pair(root, args.pair, args.end, args.attempt)
        return
    from backtest_comparison.controller import run_comparison, snapshot
    if args.resume:
        conditions = json.loads((root/"conditions.json").read_text())
    else:
        dates = [datetime.fromisoformat(value) for value in (args.start,args.pilot_to,args.max_to)]
        if any(date.tzinfo is None or date.utcoffset().total_seconds()!=0 or date.hour or date.minute or date.second or date.microsecond for date in dates):
            parser.error("comparison ranges must use UTC midnight boundaries")
        if not dates[0] < dates[1] <= dates[2]:
            parser.error("require from < pilot-to <= max-to")
        repo = Path(__file__).resolve().parents[1]
        conditions = snapshot(root, repo, args.main_analysis_dir.resolve(), args.data_root.resolve(),
                              args.pairs, args.start, args.pilot_to, args.max_to)
    run_comparison(root, conditions, args.workers)


if __name__ == "__main__":
    main()
