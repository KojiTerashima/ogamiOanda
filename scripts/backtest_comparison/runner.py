"""Run three observable layers without changing production trading behavior."""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta
import hashlib
import json
from pathlib import Path
import time

import pandas as pd

from ogami_oanda.adapters.legacy.main_analysis.backend import MainSourceAnalysis
from ogami_oanda.application.services.historical_market import HistoricalMarket
from ogami_oanda.domain.analysis.main_contracts import AnalysisRequest
from ogami_oanda.entrypoints.backtest_run import run_backtest
from ogami_oanda.strategy.original.strategy import OriginalStrategy

from .common import JsonLines, compare_candidates, differences, digest, plain, write_json
from .data import Dataset
from .execution import classify_execution, normalize_main, replay_order, utc
from .native import NativeAnalysis, NativeInspection, OfflineRuntime, comparable_candidate, inspection_sources


def deny_network():
    """Install once in a dedicated worker, including libraries imported by source code."""
    import sys

    def audit(event, args):
        if event in {"socket.connect", "socket.connect_ex", "socket.getaddrinfo", "socket.bind"}:
            raise RuntimeError("comparison worker forbids network access")
        if event == "open" and isinstance(args[0], (str, bytes)):
            name = str(args[0]).replace("\\", "/")
            if name.endswith(("/tokens.py", "/config/settings.yaml")):
                raise RuntimeError("comparison worker forbids private configuration")
    sys.addaudithook(audit)


def error_record(error):
    return {"type": type(error).__name__, "message": str(error)}


def input_record(request):
    return {"pair": request.pair, "decision_time": utc(request.decision_time),
            "evaluation_time": utc(request.evaluation_time or request.decision_time),
            "current_price": request.current_price, "risk_yen": request.risk_yen,
            "frames": plain(request.candle_frames)}


def evaluation_facts(evaluation):
    return {key: {"completed_frame": plain(peak.completed_df_r), "peaks": plain(peak.peaks_original),
                  "skipped": plain(peak.skipped_peaks), "skipped_hard": plain(peak.skipped_peaks_hard)}
            for key,peak in evaluation.peaks.items()}


class Artifacts:
    def __init__(self, directory, pair):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=False)
        self.pair = pair
        self.trace = JsonLines(self.directory / "analysis.jsonl")
        self.ledger = JsonLines(self.directory / "differences.jsonl")
        self.trades = JsonLines(self.directory / "isolated-orders.jsonl")
        self.categories = Counter()
        self.first_examples = {}

    def difference(self, stage, at, category, details, request=None):
        self.categories[f"{stage}:{category}"] += 1
        key = f"{stage}-{category}"
        evidence = None
        if key not in self.first_examples:
            evidence = f"examples/{key}.json"
            self.first_examples[key] = evidence
            write_json(self.directory / evidence, {"pair": self.pair, "stage": stage, "at": at,
                       "category": category, "details": details,
                       "input": input_record(request) if request is not None else None})
        self.ledger.add({"pair": self.pair, "stage": stage, "at": at, "category": category,
                         "details": details, "example": evidence})

    def close(self):
        for stream in (self.trace, self.ledger, self.trades):
            stream.close()


def verify_aggregation(dataset, start, end, artifacts):
    market = HistoricalMarket(dataset.pair, dict.fromkeys(("M5", "M30", "H1", "S5"), 250))
    count = 0
    failures = 0
    for candle in dataset.candles(start-timedelta(days=28), end):
        market.advance(candle)
        if candle.end < start or candle.end >= end or int(candle.end.timestamp()) % 300:
            continue
        expected, _, _ = dataset.frames(candle.end)
        for foot, frame in expected.items():
            columns = ["time", "open", "high", "low", "close", "volume", "complete"]
            actual = market.candles(dataset.pair, foot, 250)
            delta = differences(frame[columns], actual[columns], dataset.pair)
            if delta:
                failures += 1
                artifacts.difference("data", candle.end.isoformat(), "aggregation", {"timeframe":foot,"differences":delta[:30]})
        count += 1
    return {"checked_boundaries": count, "mismatched_frames": failures, "gaps": market.gap_count}


def run_analysis(dataset, sources, start, end, artifacts, progress):
    native = NativeAnalysis(sources)
    backend = MainSourceAnalysis(source_directory=sources.directory, analysis_name="resistance_breakout")
    inspection = NativeInspection(sources, dataset.pair)
    baseline = {}
    counts = Counter()
    main_pnl = []
    broker_pnl = []
    closes = Counter()
    # The native Inspection slices 721 M5, 241 M30, 250 H1 rows with anaN=60.
    native_windows = {"M5": 721, "M30": 241, "H1": 250}
    times = pd.date_range(start, end, freq="5min", inclusive="left")
    with OfflineRuntime(sources=sources) as calendar_runtime:
        opened = calendar_runtime.load("fCandleDataQuality").oanda_market_open_mask(times)
    closure_verified = False
    try:
        for number, at in enumerate(times):
            if number % 24 == 0:
                progress("analysis", at.isoformat(), dict(counts))
            if not opened[number] and closure_verified:
                counts["scheduled"] += 1
                counts["market_closed"] += 1
                artifacts.trace.add({"at":at.isoformat(), "status":"market_closed",
                                     "validation":"source calendar; both paths checked at closure entry"})
                baseline[at.isoformat()] = {"status":"market_closed", "candidates":[]}
                continue
            if opened[number]:
                closure_verified = False
            frames, current, observed_end = dataset.frames(at, native_windows)
            request = AnalysisRequest(dataset.pair, at, current, frames, evaluation_time=at, risk_yen=500)
            stamp = at.isoformat()
            counts["scheduled"] += 1
            record = {"at": stamp, "last_observed_end": observed_end.isoformat(), "input_sha256": digest(input_record(request))}
            native_error = adapter_error = None
            a = b = None
            try:
                a = native.evaluate(request)
            except Exception as error:
                native_error = error_record(error)
            try:
                b = backend.evaluate(request)
                if b.status != "ok":
                    adapter_error = {"type": "AnalysisNotReady", "message": b.diagnostics.get("reason", "not ready")}
            except Exception as error:
                adapter_error = error_record(error)
            closed_message = "OANDA market is closed at the decision time"
            if (not opened[number] and native_error and adapter_error
                    and native_error["message"] == adapter_error["message"] == closed_message):
                closure_verified = True
                counts["market_closed"] += 1
                record.update(status="market_closed", main_error=native_error, ogami_error=adapter_error,
                              validation="both full evaluation paths")
                artifacts.trace.add(record)
                baseline[stamp] = {"status":"market_closed", "candidates":[]}
                continue
            if native_error or adapter_error:
                counts["errors_or_not_ready"] += 1
                record.update(main_error=native_error, ogami_error=adapter_error)
                artifacts.difference("A", stamp, "evaluation_unavailable", record, request)
                baseline[stamp] = {"status":"unavailable", "candidates": [], "input_sha256": record["input_sha256"]}
                artifacts.trace.add(record)
                continue
            counts["evaluated"] += 1
            ac = [comparable_candidate(c) for c in a["candidates"]]
            bc = [comparable_candidate(c) for c in b.candidates]
            candidates_delta = compare_candidates(ac, bc, dataset.pair)
            frames_delta = differences(a["frames"], b.frames, dataset.pair)
            facts_delta = differences(a["facts"], evaluation_facts(b), dataset.pair)
            signals_delta = differences(a["signals"], b.diagnostics["analysis"], dataset.pair)
            for category, delta in (("input_enrichment", frames_delta), ("indicators_peaks", facts_delta),
                                    ("resistance_candidates", signals_delta), ("candidate_conversion", candidates_delta)):
                if delta:
                    counts["mismatches"] += 1
                    artifacts.difference("A", stamp, category, {"count":len(delta), "differences":delta[:30]}, request)
            counts["candidates"] += len(ac)
            record.update(status="ok", candidates=ac, signals_sha256=digest(a["signals"]), main_facts_sha256=digest(a["facts"]),
                          ogami_facts_sha256=digest(evaluation_facts(b)),
                          main_frames_sha256=digest(a["frames"]), ogami_frames_sha256=digest(b.frames))
            baseline[stamp] = {"status":"ok", "candidates": ac, "input_sha256":record["input_sha256"],
                               "current_price":current, "windows":native_windows}
            artifacts.trace.add(record)
            for ordinal, candidate in enumerate(ac):
                horizon = min(end, at.to_pydatetime()+timedelta(minutes=candidate["order_timeout_min"]+candidate["trade_timeout_min"], seconds=5))
                frame = dataset.inspection_frame(at, horizon)
                result = inspection.evaluate(at, candidate, frame)
                main = normalize_main(result, candidate)
                ogami, events = replay_order(dataset.pair, at, candidate, dataset.candles(at, horizon, fixed=True))
                delta, causes = classify_execution(main, ogami, candidate, events, dataset)
                counts["filled"] += int(main["filled"])
                counts["isolated_ogami_filled"] += int(ogami["filled"])
                closes[f"main:{main['reason']}"] += 1
                closes[f"ogami:{ogami['reason']}"] += 1
                if main["pnl_quote"] is not None:
                    main_pnl.append(main["pnl_quote"])
                if ogami["pnl_quote"] is not None:
                    broker_pnl.append(ogami["pnl_quote"])
                row = {"at":stamp, "ordinal":ordinal, "candidate":candidate, "main":main, "ogami":ogami,
                       "main_raw":result, "events":events, "differences":delta, "causes":causes}
                artifacts.trades.add(row)
                for cause in causes:
                    artifacts.difference("B", stamp, cause, row, request)
        return baseline, {**dict(counts), "main_counterfactual_pnl_quote":sum(main_pnl),
                          "ogami_isolated_pnl_quote":sum(broker_pnl),
                          "main_win_rate":sum(v>0 for v in main_pnl)/len(main_pnl) if main_pnl else None,
                          "ogami_isolated_win_rate":sum(v>0 for v in broker_pnl)/len(broker_pnl) if broker_pnl else None,
                          "close_reasons":dict(closes)}
    finally:
        inspection.close()


class ObservingBackend(MainSourceAnalysis):
    def __init__(self, sources, dataset, baseline, artifacts, label):
        super().__init__(source_directory=sources.directory, analysis_name="resistance_breakout")
        self.dataset, self.baseline, self.artifacts, self.label = dataset, baseline, artifacts, label
        self.trace = JsonLines(artifacts.directory / f"{label}-analysis.jsonl")
        self.counts = Counter()
        self.native = NativeAnalysis(sources)

    def evaluate(self, request):
        result = super().evaluate(request)
        self.counts["evaluated"] += 1
        self.counts["candidates"] += len(result.candidates)
        self.counts["intents"] += len(result.intents)
        if result.status != "ok":
            self.counts["not_ready"] += 1
        stamp = utc(request.decision_time)
        current = [comparable_candidate(c) for c in result.candidates]
        row = {"at":stamp, "evaluation_time":utc(request.evaluation_time), "status":result.status,
               "current_price":request.current_price, "input_sha256":digest(input_record(request)),
               "windows":{k:len(v) for k,v in request.candle_frames.items()}, "candidates":current,
               "withheld":plain(result.diagnostics.get("withheld", [])),
               "reason":result.diagnostics.get("reason")}
        main = self.baseline.get(stamp)
        if main is not None and main["status"] == "ok":
            delta = compare_candidates(main["candidates"], current, request.pair)
            if delta:
                # Verify the actual continuous input against native source too;
                # do not guess an adapter defect from changed evaluation inputs.
                reference = self.native.evaluate(request)
                identical_input_delta = compare_candidates(reference["candidates"], current, request.pair)
                category = "same_input_candidate_mismatch" if identical_input_delta else "native_window_or_evaluation_input"
                self.artifacts.difference(self.label, stamp, category,
                                          {"differences":delta, "same_input_differences":identical_input_delta,
                                           "main":main, "continuous":row}, request)
        self.trace.add(row)
        return result


def run_continuous(dataset, sources, baseline, start, end, artifacts, fixed, progress):
    label = "C-fixed" if fixed else "C-mba"
    backend = ObservingBackend(sources, dataset, baseline, artifacts, label)
    strategy = OriginalStrategy(dataset.pair, risk_yen=500, analysis_backend=backend)
    try:
        summary = run_backtest(strategy, "main-comparison", dataset.pair,
                    dataset.candles(start-timedelta(days=28), end, fixed=fixed), start, end,
                    initial_balance=1_000_000 if dataset.pair=="USD_JPY" else 10_000,
                    output_dir=artifacts.directory/label, slippage_pips=.5,
                    metadata={"price_mode":"MID_FIXED_SPREAD" if fixed else "MBA", "fixed_spread_pips":.8 if fixed else None,
                              "data_sha256":dataset.manifest_sha256, "comparison":True},
                    progress=lambda at:progress(label, at.isoformat(), dict(backend.counts)),
                    analysis_name="resistance_breakout")
        return {"analysis":dict(backend.counts), "summary":summary, "analysis_sha256":backend.trace.hasher.hexdigest()}
    finally:
        backend.trace.close()


def normalized_hashes(directory):
    result = {}
    for path in sorted(Path(directory).rglob("*")):
        if path.is_file() and (path.suffix in {".csv", ".jsonl"} or path.name == "summary.json"):
            # All serialized records are deterministic; run/progress manifests contain paths/timings.
            result[str(path.relative_to(directory))] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def run_pair(root, pair, end, attempt):
    deny_network()
    root = Path(root)
    conditions = json.loads((root/"conditions.json").read_text())
    start = datetime.fromisoformat(conditions["from"])
    end = datetime.fromisoformat(end)
    artifacts = Artifacts(root/f"{start.date()}_{end.date()}"/pair/attempt, pair)
    began = time.monotonic()

    def progress(stage, at, counts):
        write_json(artifacts.directory/"progress.json", {"status":"running", "stage":stage, "at":at,
                   "counts":counts, "elapsed_seconds":time.monotonic()-began})
        print(f"{pair} {attempt} {stage} {at} {counts}", flush=True)

    try:
        progress("load", start.isoformat(), {})
        dataset = Dataset.from_store(root/"source/history"/pair, pair, start-timedelta(days=28), end)
        sources = inspection_sources(root/"source/main")
        quality = dataset.quality(start, end)
        write_json(artifacts.directory/"data-quality.json", quality)
        aggregation = verify_aggregation(dataset, start, end, artifacts)
        if aggregation["mismatched_frames"]:
            raise ValueError("independent aggregation disagrees with HistoricalMarket")
        baseline, analysis = run_analysis(dataset, sources, start, end, artifacts, progress)
        fixed = run_continuous(dataset, sources, baseline, start, end, artifacts, True, progress)
        mba = run_continuous(dataset, sources, baseline, start, end, artifacts, False, progress)
        needs_extension = (not analysis.get("evaluated") or not analysis.get("candidates") or not analysis.get("filled")
                           or not fixed["analysis"].get("evaluated") or not fixed["summary"]["trade_count"]
                           or not mba["analysis"].get("evaluated") or not mba["summary"]["trade_count"]
                           or any("unclassified" in key or "same_input" in key or key.startswith("A:")
                                  for key in artifacts.categories))
        artifacts.close()
        summary = {"status":"complete", "pair":pair, "from":start.isoformat(), "to":end.isoformat(),
                   "aggregation":aggregation, "analysis":analysis, "fixed":fixed, "mba":mba,
                   "categories":dict(artifacts.categories), "examples":artifacts.first_examples,
                   "needs_extension":needs_extension,
                   "limitations":["Main totals are independent, counterfactual orders; equity/DD are not comparable.",
                                  "No-tick S5 rows are not synthesized; common observed data only.",
                                  "The isolated broker driver checks deadlines on every S5 end; C uses production management."]}
        write_json(artifacts.directory/"result.json", summary)
        write_json(artifacts.directory/"normalized-hashes.json", normalized_hashes(artifacts.directory))
        write_json(artifacts.directory/"progress.json", {"status":"complete", "elapsed_seconds":time.monotonic()-began})
        return str(artifacts.directory)
    except BaseException as error:
        artifacts.close()
        write_json(artifacts.directory/"result.json", {"status":"failed", "error":error_record(error)})
        raise
