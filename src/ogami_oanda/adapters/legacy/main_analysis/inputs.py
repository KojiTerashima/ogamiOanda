"""Translate candle inputs using the pinned source's own preparation routines."""

from __future__ import annotations

from math import isfinite

import pandas as pd

from ogami_oanda.domain.analysis.main_contracts import (
    AnalysisIntegrityError, AnalysisNotReady, AnalysisRequest,
)


def jst_time(value):
    stamp = pd.Timestamp(value)
    if pd.isna(stamp):
        raise AnalysisIntegrityError("analysis time is missing")
    return stamp.tz_localize("Asia/Tokyo") if stamp.tzinfo is None else stamp.tz_convert("Asia/Tokyo")


class SnapshotPrices:
    def __init__(self, request):
        self.values = {request.pair: float(request.current_price)}
        if request.usd_jpy_rate is not None:
            if not isfinite(float(request.usd_jpy_rate)) or request.usd_jpy_rate <= 0:
                raise AnalysisIntegrityError("USD/JPY conversion rate must be positive")
            self.values["USD_JPY"] = float(request.usd_jpy_rate)

    def NowPrice_exe(self, pair):
        value = self.values.get(pair)
        return {"error": 1} if value is None else {"error": 0, "data": {"mid": value, "bid": value, "ask": value}}


def prepare_frames(runtime, request):
    source = runtime.load("classOanda")
    pair = runtime.load("fGeneric").currency_pair(request.pair)
    decision = jst_time(request.decision_time)
    frames = {}
    for timeframe, original in request.candle_frames.items():
        if timeframe not in {"M5", "M30", "H1", "S5", "M1"}:
            raise AnalysisIntegrityError(f"unsupported timeframe: {timeframe}")
        if not isinstance(original, pd.DataFrame):
            raise AnalysisIntegrityError(f"{timeframe} must be a DataFrame")
        if original.empty:
            raise AnalysisNotReady(f"{timeframe} candles are unavailable")
        missing = {"open", "high", "low", "close"} - set(original.columns)
        if missing:
            raise AnalysisIntegrityError(f"{timeframe} missing OHLC columns: {sorted(missing)}")
        frame = original.copy(deep=True)
        if "time_jp_dt" in frame:
            times = pd.to_datetime(frame["time_jp_dt"])
        elif "time_jp" in frame:
            times = pd.to_datetime(frame["time_jp"])
        elif "time" in frame:
            times = pd.to_datetime(frame["time"], utc=True)
        else:
            raise AnalysisIntegrityError(f"{timeframe} missing candle timestamps")
        if times.isna().any():
            raise AnalysisIntegrityError(f"{timeframe} has missing timestamps")
        if times.dt.tz is None:
            times = times.dt.tz_localize("Asia/Tokyo")
        else:
            times = times.dt.tz_convert("Asia/Tokyo")
        frame["time_jp_dt"] = times.dt.tz_localize(None)
        frame = frame[times <= decision].copy()
        if frame.empty:
            raise AnalysisNotReady(f"{timeframe} has no candles before decision time")
        frame = frame.sort_values("time_jp_dt").reset_index(drop=True)
        if frame["time_jp_dt"].duplicated().any():
            raise AnalysisIntegrityError(f"{timeframe} contains duplicate timestamps")
        frame["time_jp"] = frame["time_jp_dt"].dt.strftime("%Y/%m/%d %H:%M:%S")
        frame["time"] = frame["time_jp_dt"].dt.tz_localize("Asia/Tokyo").dt.tz_convert("UTC").astype(str)
        if "is_complete" in frame and "complete" in frame and not frame["is_complete"].equals(frame["complete"]):
            raise AnalysisIntegrityError(f"{timeframe} completion flags disagree")
        complete = frame.get("is_complete", frame.get("complete"))
        if complete is None and request.mode == "live":
            raise AnalysisIntegrityError(f"{timeframe} live candles require a completion flag")
        if complete is not None and not complete.isin([True, False]).all():
            raise AnalysisIntegrityError(f"{timeframe} contains invalid completion flags")
        for column in ("open", "high", "low", "close"):
            frame[column] = pd.to_numeric(frame[column], errors="raise")
            if not frame[column].map(isfinite).all():
                raise AnalysisIntegrityError(f"{timeframe} contains nonfinite OHLC")
        frame["mid"] = [{"o": row.open, "h": row.high, "l": row.low, "c": row.close} for row in frame.itertuples()]
        frame["complete"] = True if complete is None else complete
        frame = source.add_basic_data(frame, pair)
        frame = source.add_rsi(frame)
        if timeframe != "S5":
            frame = source.add_bb_data(frame, pair)
        if complete is not None:
            frame["complete"] = complete.to_numpy()
            frame["is_complete"] = complete.to_numpy()
        frames[timeframe] = frame.iloc[::-1].reset_index(drop=True)
    return frames


def prepare_candles(runtime, request: AnalysisRequest):
    if request.pair not in {"USD_JPY", "EUR_USD", "AUD_USD"}:
        raise AnalysisIntegrityError("unsupported currency pair")
    for timeframe, actual in request.source_granularities.items():
        if timeframe not in {"M5", "M30", "H1", "S5", "M1"} or (timeframe != actual and (timeframe, actual) != ("M30", "H1")):
            raise AnalysisIntegrityError(f"unsupported source granularity: {timeframe}/{actual}")
    if request.mode not in {"inspection", "live"}:
        raise AnalysisIntegrityError("mode must be inspection or live")
    if not isfinite(float(request.current_price)) or request.current_price <= 0:
        raise AnalysisIntegrityError("current price must be positive and finite")
    if not {"M5", "H1"} <= request.candle_frames.keys():
        raise AnalysisNotReady("main analysis requires M5 and H1 candles")
    frames = prepare_frames(runtime, request)
    native = runtime.load("classCandleAnalysis")

    class InputCandles(native.candleAnalysis):
        def prepare_timeframe_dataframes(self):
            self.analysis_mode = request.mode
            if request.source_granularities.get("M30") == "H1":
                self.m30_uses_h1_fallback = True
            return super().prepare_timeframe_dataframes()

    candles = InputCandles(
        base_oa=SnapshotPrices(request), pair=request.pair,
        m5_original_df_r=frames["M5"], h1_original_df_r=frames["H1"],
        m30_original_df_r=frames.get("M30"), s5_original_df_r=frames.get("S5"),
        current_price=request.current_price,
        decision_time=jst_time(request.decision_time).tz_localize(None),
        current_price_source="supplied_quote",
    )
    candles.require_basic_analysis()
    return candles, frames


def line_view(runtime, request, candles):
    source = runtime.load("fLineAnalysis")

    class AnalysisView(source.MainAnalysis):
        def main(self):
            # The original constructor prepares attributes; evaluation is explicit.
            pass

    view = AnalysisView(candles, mode=request.mode)
    if request.risk_yen is not None:
        if not isfinite(float(request.risk_yen)) or request.risk_yen <= 0:
            raise AnalysisIntegrityError("risk_yen must be positive and finite")
        source.gl_risk_yen = float(request.risk_yen)
        source.gl_live_usd_jpy_risk_yen = float(request.risk_yen)
    # Avoid native CSV lookup. Inspection may only use the supplied historical rates.
    rates = pd.Series(dtype=float)
    if request.conversion_candles is not None:
        frame = request.conversion_candles.copy(deep=True)
        times = pd.to_datetime(frame["time_jp"])
        if times.dt.tz is not None:
            times = times.dt.tz_convert("Asia/Tokyo").dt.tz_localize(None)
        rates = pd.Series(frame["close"].astype(float).to_numpy(), index=times).sort_index()
        if rates.index.duplicated().any() or not rates.map(lambda x: isfinite(x) and x > 0).all():
            raise AnalysisIntegrityError("invalid conversion candles")
    elif request.usd_jpy_rate is not None:
        rates = pd.Series([float(request.usd_jpy_rate)], index=[jst_time(request.decision_time).tz_localize(None)])
    source.LineOrderCoordinator._inspection_usd_jpy_close = rates
    return view


def peak_objects(candles):
    return {
        "M5": candles.peaks_class, "H1": candles.peaks_class_hour,
        "M30": candles.peaks_class_m30,
    }
