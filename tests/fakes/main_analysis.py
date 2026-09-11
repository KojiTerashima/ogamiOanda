"""Contiguous raw candles for main-source adapter contracts."""

import numpy as np
import pandas as pd

from ogami_oanda.domain.analysis.main_contracts import AnalysisRequest


def request_for(pair="USD_JPY", *, mode="inspection", latest="2026-09-11 12:00:00"):
    pip = 0.01 if pair == "USD_JPY" else 0.0001
    base = {"USD_JPY": 150, "EUR_USD": 1.1, "AUD_USD": 0.7}[pair]
    digits = 3 if pair == "USD_JPY" else 5
    frames = {}
    for timeframe, frequency in {"M5": "5min", "M30": "30min", "H1": "h", "S5": "5s"}.items():
        times = pd.date_range(end=pd.Timestamp(latest).floor(frequency), periods=270, freq=frequency)
        close = np.round(base + np.sin(np.arange(270) / 2) * 12 * pip + np.arange(270) * .04 * pip, digits)
        opens = np.round(close - 2 * pip, digits)
        frames[timeframe] = pd.DataFrame({
            "time_jp": times.strftime("%Y/%m/%d %H:%M:%S"),
            "open": opens, "close": close, "high": close + 4 * pip,
            "low": opens - 4 * pip, "complete": True,
        }).iloc[::-1].reset_index(drop=True)
    return AnalysisRequest(pair, latest, float(frames["M5"].iloc[0]["close"]), frames, mode=mode)
