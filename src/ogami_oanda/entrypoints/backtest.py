"""Fetch resumable S5 history or run a credential-free strategy backtest."""

from __future__ import annotations

import argparse
from datetime import timedelta
import hashlib
import json
import math
from pathlib import Path
import sys

from ogami_oanda.entrypoints.main_analysis import bind_main_analysis
from ogami_oanda.adapters.legacy.main_analysis.source import DEFAULT_SOURCE_DIRECTORY
from ogami_oanda.adapters.repositories.historical_store import HistoricalStore, file_hash, read_mid_csv
from ogami_oanda.application.services.historical_market import HistoricalMarket
from ogami_oanda.application.services.history_download import download_history
from ogami_oanda.domain.market.history import GRANULARITY_SECONDS, utc_time
from ogami_oanda.entrypoints.backtest_run import run_backtest
from ogami_oanda.strategy.shared.contracts import strategy_data_requirements
from ogami_oanda.strategy.shared.loader import load_strategy


def source_hash() -> str:
    package = Path(__file__).resolve().parents[1]
    digest = hashlib.sha256()
    for path in sorted(package.rglob("*.py")):
        digest.update(path.relative_to(package).as_posix().encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def select_strategy(args) -> tuple:
    root = Path(__file__).resolve().parents[1] / "strategy"
    if args.strategy_py:
        if not args.strategy_yaml:
            raise ValueError("--strategy-py requires --strategy-yaml")
        loaded = load_strategy(args.strategy_py, args.strategy_yaml)
        strategy, identity = loaded.strategy, loaded.strategy_id
        hashes = {"strategy_python_sha256": file_hash(loaded.python_path), "strategy_yaml_sha256": file_hash(loaded.yaml_path)}
    elif args.strategy_yaml:
        raise ValueError("--strategy-yaml requires --strategy-py")
    elif args.strategy == "original":
        from ogami_oanda.strategy.original.strategy import create_strategy

        config = {"pair": args.pair, "risk_yen": args.risk_yen, "line_units": args.line_units}
        strategy = create_strategy(config)
        code = file_hash(root / "original" / "strategy.py")
        config_hash = hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest()
        identity = f"strategy-{code[:16]}-{config_hash[:16]}"
        hashes = {"strategy_python_sha256": code, "strategy_config_sha256": config_hash}
    else:
        loaded = load_strategy(root / "matcha" / "strategy.py", root / "matcha" / "parameters.yaml")
        strategy, identity = loaded.strategy, loaded.strategy_id
        hashes = {"strategy_python_sha256": file_hash(loaded.python_path), "strategy_yaml_sha256": file_hash(loaded.yaml_path)}
    if args.command == "run":
        bind_main_analysis(strategy, mode="inspection", main_analysis_dir=args.main_analysis_dir)
    configured_pair = getattr(strategy, "pair", args.pair)
    if configured_pair != args.pair:
        raise ValueError("strategy pair does not match --pair")
    return strategy, identity, hashes


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    commands = result.add_subparsers(dest="command", required=True)
    for command in ("fetch", "run"):
        sub = commands.add_parser(command)
        sub.add_argument("--pair", choices=("USD_JPY", "EUR_USD", "AUD_USD"), required=True)
        sub.add_argument("--from", dest="start", type=utc_time, required=True, help="inclusive timestamp with Z/offset")
        sub.add_argument("--to", dest="end", type=utc_time, required=True, help="exclusive timestamp with Z/offset")
        selection = sub.add_mutually_exclusive_group(required=True)
        selection.add_argument("--strategy", choices=("original", "matcha"))
        selection.add_argument("--strategy-py")
        sub.add_argument("--strategy-yaml")
        sub.add_argument("--risk-yen", type=float, default=500, help="named original's existing risk parameter")
        sub.add_argument("--line-units", type=int, default=1, help="named original's existing base units")
        if command == "fetch":
            sub.add_argument("--data-dir", required=True)
            sub.add_argument("--config", required=True, help="ignored credential configuration (fetch only)")
            sub.add_argument("--account", default="primary")
            sub.add_argument("--warmup-days", type=int, help="override automatically sized warmup history")
        else:
            sub.add_argument("--main-analysis-dir", default=DEFAULT_SOURCE_DIRECTORY, metavar="PATH",
                             help="main source directory for original (default: ../main, relative to working directory)")
            data = sub.add_mutually_exclusive_group(required=True)
            data.add_argument("--data-dir")
            data.add_argument("--mid-csv", help="ascending Mid OHLC CSV (optionally .gz)")
            sub.add_argument("--fixed-spread-pips", type=float)
            sub.add_argument("--slippage-pips", type=float, default=0)
            sub.add_argument("--initial-balance", type=float, required=True, help="quote-currency units; no margin model")
            sub.add_argument("--output-dir", required=True, help="new directory; never overwrite results")
    return result


def _fetch(args, strategy) -> None:
    # Imports and construction for authenticated I/O exist only on fetch.
    from ogami_oanda.adapters.oanda.client import OandaClient
    from ogami_oanda.adapters.oanda.history import OandaHistorySource
    from ogami_oanda.infrastructure.config.loader import load_settings
    from ogami_oanda.infrastructure.runtime import SystemClock, system_sleep

    if args.end > SystemClock().now():
        raise ValueError("fetch end must not be in the future")
    requirements = strategy_data_requirements(strategy)
    seconds = max((GRANULARITY_SECONDS[key] * (count + 1) for key, count in requirements.items()), default=0)
    days = args.warmup_days if args.warmup_days is not None else math.ceil(seconds * 2 / 86400) + 7
    if days < 0:
        raise ValueError("warmup days must be nonnegative")
    start = (args.start - timedelta(days=days)).replace(hour=0, minute=0, second=0, microsecond=0)
    store = HistoricalStore(args.data_dir, args.pair)
    settings = load_settings(args.config)
    source = OandaHistorySource(OandaClient(settings.account(args.account)))
    with store.download_lock():
        download_history(source, store, start, args.end, sleep=system_sleep,
                         progress=lambda at: print(f"[FETCH] acquired through {at.isoformat()}", flush=True))
    market = HistoricalMarket(args.pair, requirements)
    for candle in store.read(start, args.start):
        market.advance(candle)
    if not market.ready:
        raise ValueError("history acquired but warmup unavailable; increase --warmup-days")
    print("Historical acquisition complete; warmup available.")


def _run(args, strategy, identity, hashes) -> dict:
    if Path(args.output_dir).exists():
        raise FileExistsError("output directory already exists")
    metadata = {**hashes, "source_sha256": source_hash()}
    if args.mid_csv:
        # Exhaust once before orders exist, so corrupt late rows cannot silently
        # produce a seemingly complete result. Each pass remains streaming.
        for _ in read_mid_csv(args.mid_csv, args.pair, args.fixed_spread_pips):
            pass
        values = read_mid_csv(args.mid_csv, args.pair, args.fixed_spread_pips)
        metadata.update(data_sha256=file_hash(Path(args.mid_csv)), price_mode="MID_FIXED_SPREAD",
                        fixed_spread_pips=args.fixed_spread_pips)
    else:
        if args.fixed_spread_pips is not None:
            raise ValueError("--fixed-spread-pips is only valid with --mid-csv")
        store = HistoricalStore(args.data_dir, args.pair)
        if not store.manifest["intervals"]:
            raise ValueError("historical dataset has no acquired intervals")
        earliest = min(utc_time(interval["from"]) for interval in store.manifest["intervals"])
        store.validate(earliest, args.end)
        values = store.read(earliest, args.end)
        manifest_json = json.dumps(store.manifest, sort_keys=True, separators=(",", ":"),
                                   ensure_ascii=False, allow_nan=False)
        metadata.update(
            data_sha256=hashlib.sha256(manifest_json.encode("utf-8")).hexdigest(),
            data_manifest=json.loads(manifest_json),
            data_manifest_encoding="utf-8;json:sort_keys=true,separators=comma:colon,ensure_ascii=false",
            price_mode="MBA",
        )
    return run_backtest(strategy, identity, args.pair, values, args.start, args.end,
                        initial_balance=args.initial_balance, output_dir=args.output_dir,
                        slippage_pips=args.slippage_pips, metadata=metadata, main_analysis_dir=args.main_analysis_dir,
                        progress=lambda at: print(f"[REPLAY] {at.isoformat()}", flush=True))


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.start >= args.end or any(t.microsecond or t.second % 5 for t in (args.start, args.end)):
            raise ValueError("range must increase and align to S5")
        strategy, identity, hashes = select_strategy(args)
        if args.command == "fetch":
            _fetch(args, strategy)
        else:
            summary = _run(args, strategy, identity, hashes)
            print(json.dumps(summary, ensure_ascii=False, sort_keys=True, allow_nan=False))
        return 0
    except (ValueError, OSError, RuntimeError, KeyError) as error:
        # Authenticated failures can contain private URLs in lower-level errors.
        # Do not render arbitrary exception bodies from the fetch composition.
        detail = type(error).__name__ if args.command == "fetch" else str(error)
        print(f"Backtest {args.command} failed: {detail}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
