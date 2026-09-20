"""Unmodified main calculations with explicit offline environment boundaries."""

from __future__ import annotations

from contextlib import nullcontext
from dataclasses import asdict
from types import ModuleType

import pandas as pd

from ogami_oanda.adapters.legacy.main_analysis.loader import SourceRuntime
from ogami_oanda.adapters.legacy.main_analysis.source import MainSources, read_sources
from ogami_oanda.adapters.legacy.main_analysis.values import plain as source_plain

from .common import plain


EXTRA_MODULES = ("classInspection", "classStrategyRegime", "fAnalysis_order_Main")


def inspection_sources(directory):
    sources = read_sources(directory)
    contents = dict(sources.contents)
    for name in EXTRA_MODULES:
        contents[name] = (sources.directory / f"{name}.py").read_bytes()
    return MainSources(sources.directory, contents)


class OfflineRuntime(SourceRuntime):
    def _import(self, name, globals=None, locals=None, fromlist=(), level=0):
        if name == "fFlipWatch":
            # Only registration side effects for live flip; inspection never invokes it.
            return self.shims.setdefault(name, ModuleType(name))
        return super()._import(name, globals, locals, fromlist, level)

    def _shim(self, name):
        module = super()._shim(name)
        if name == "send_notice":
            module.inspection_notice_scope = nullcontext
        return module


def prepare_native_frames(runtime, request):
    """Call main's enrichment functions independently of the ogami input adapter."""
    source = runtime.load("classOanda")
    pair = runtime.load("fGeneric").currency_pair(request.pair)
    result = {}
    for timeframe, supplied in request.candle_frames.items():
        frame = supplied.copy(deep=True)
        if "time" in frame:
            times = pd.to_datetime(frame["time"], utc=True).dt.tz_convert("Asia/Tokyo").dt.tz_localize(None)
        else:
            times = pd.to_datetime(frame["time_jp"])
        decision = pd.Timestamp(request.decision_time)
        if decision.tzinfo is not None:
            decision = decision.tz_convert("Asia/Tokyo").tz_localize(None)
        frame["time_jp_dt"] = times
        frame = frame.loc[times <= decision].sort_values("time_jp_dt").reset_index(drop=True)
        frame["time_jp"] = frame.time_jp_dt.dt.strftime("%Y/%m/%d %H:%M:%S")
        frame["time"] = frame.time_jp_dt.dt.tz_localize("Asia/Tokyo").dt.tz_convert("UTC").astype(str)
        flags = frame.get("complete", pd.Series(True, index=frame.index)).copy()
        frame["mid"] = [{"o": row.open, "h": row.high, "l": row.low, "c": row.close} for row in frame.itertuples()]
        frame["complete"] = flags
        frame = source.add_rsi(source.add_basic_data(frame, pair))
        if timeframe != "S5":
            frame = source.add_bb_data(frame, pair)
        frame["complete"] = flags.to_numpy()
        frame["is_complete"] = flags.to_numpy()
        result[timeframe] = frame.iloc[::-1].reset_index(drop=True)
    return result


def native_candidate(order):
    # Do not call from_native_order here: this is its independent reference.
    metadata = source_plain({**order.order_json, **order.exe_order_plan})
    return {"pair": order.instrument, "direction": int(order.direction), "order_type": order.ls_type,
            "target_price": float(order.target_price), "take_profit_price": float(order.tp_price),
            "stop_loss_price": float(order.lc_price), "units": int(order.units), "name": order.name,
            "priority": int(order.priority), "order_timeout_min": int(order.order_timeout_min),
            "trade_timeout_min": int(order.trade_timeout_min), "decision_time": str(order.decision_time),
            "lc_change": source_plain(order.lc_change or []), "metadata": metadata}


def comparable_candidate(candidate):
    value = plain(candidate) if isinstance(candidate, dict) else plain(asdict(candidate))
    value.pop("execution", None)
    meta = value["metadata"]
    # Documented adapter annotations, not native order calculations.
    for key in ("main_analysis", "trade_timeout_enabled"):
        meta.pop(key, None)
    return value


def candle_facts(candles):
    facts = {}
    for key, peak in (("M5", candles.peaks_class), ("H1", candles.peaks_class_hour),
                      ("M30", candles.peaks_class_m30)):
        if peak is not None:
            facts[key] = {"completed_frame": plain(peak.completed_df_r),
                          "peaks": source_plain(peak.peaks_original),
                          "skipped": source_plain(peak.skipped_peaks),
                          "skipped_hard": source_plain(peak.skipped_peaks_hard)}
    return facts


class NativeAnalysis:
    def __init__(self, sources):
        self.sources = sources

    def evaluate(self, request):
        at = pd.Timestamp(request.evaluation_time or request.decision_time)
        at = at.tz_localize("Asia/Tokyo") if at.tzinfo is None else at.tz_convert("Asia/Tokyo")
        with OfflineRuntime(sources=self.sources, evaluation_time=at.to_pydatetime()) as runtime:
            frames = prepare_native_frames(runtime, request)
            decision = pd.Timestamp(request.decision_time)
            if decision.tzinfo is not None:
                decision = decision.tz_convert("Asia/Tokyo").tz_localize(None)
            candles = runtime.load("classCandleAnalysis").candleAnalysis(
                base_oa=None, pair=request.pair, target_time_jp=decision,
                m5_original_df_r=frames["M5"], h1_original_df_r=frames["H1"],
                m30_original_df_r=frames.get("M30"), s5_original_df_r=frames.get("S5"),
                current_price=request.current_price, current_price_source="supplied_quote")
            candles.require_basic_analysis()
            module = runtime.load("fResistanceBreakoutAnalysis")
            build_order = module.build_order
            signals = []

            def observe_order(**kwargs):
                signals.append(source_plain({key:value for key,value in kwargs.items()
                                             if key not in {"line_class", "context", "candle_analysis_class"}}))
                return build_order(**kwargs)

            with runtime.binding(module, "build_order", observe_order):
                orders = module.build_orders_for_decision(candles, mode="inspection")
            return {"candidates": [native_candidate(order) for order in orders],
                    "signals": {"signals": signals},
                    "facts": candle_facts(candles), "frames": plain(frames)}

    def policy(self):
        with OfflineRuntime(sources=self.sources) as runtime:
            return asdict(runtime.load("fResistanceBreakoutAnalysis").LIVE_TRIAL_POLICY_V1)


class NativeInspection:
    def __init__(self, sources, pair):
        self.runtime = OfflineRuntime(sources=sources)
        klass = self.runtime.load("classInspection").Inspection
        self.instance = klass.__new__(klass)
        self.instance.pair = pair
        self.instance.p = self.runtime.load("fGeneric").currency_pair(pair)
        self.instance.spread_pips = 0.8
        self.instance.half_spread_pips = 0.4

    def evaluate(self, decision, candidate, frame):
        at = pd.Timestamp(decision)
        at = at.tz_convert("Asia/Tokyo").tz_localize(None) if at.tzinfo else at
        plan = {**candidate.get("metadata", {}), "source": "resistance_breakout", "pair": candidate["pair"],
                "direction": candidate["direction"], "type": candidate["order_type"],
                "target_price": candidate["target_price"], "tp_price": candidate["take_profit_price"],
                "lc_price": candidate["stop_loss_price"], "units": candidate["units"],
                "order_timeout_min": candidate["order_timeout_min"], "trade_timeout_min": candidate["trade_timeout_min"],
                "assumed_stop_slippage_pips": 0.5}
        result = self.instance.inspect_order_after(at, plan, frame)
        self.runtime.output.seek(0)
        self.runtime.output.truncate()
        return plain(result)

    def close(self):
        self.runtime.close()
