from __future__ import annotations

import numpy as np
import pandas as pd

from ogami_oanda.domain.market.currency_pair import currency_pair


def add_basic_data(data_frame: pd.DataFrame, pair=None) -> pd.DataFrame:
    """Add derived candle values to canonical OHLC market data."""
    pair = pair or currency_pair("USD_JPY")
    data_frame = data_frame.copy()
    missing = {"open", "close", "high", "low"} - set(data_frame.columns)
    if missing:
        raise ValueError(f"Canonical OHLC columns required: {', '.join(sorted(missing))}")
    for column in ("open", "close", "high", "low"):
        data_frame[column] = pd.to_numeric(data_frame[column], errors="raise")
    data_frame["mid_outer"] = pair.round_price((data_frame["high"] + data_frame["low"]) / 2)
    data_frame["inner_high"] = data_frame[["open", "close"]].max(axis=1)
    data_frame["inner_low"] = data_frame[["open", "close"]].min(axis=1)
    data_frame["body"] = data_frame["close"] - data_frame["open"]
    data_frame["body_abs"] = data_frame["body"].abs()
    data_frame["direction"] = np.sign(data_frame["body"])
    data_frame["moves"] = data_frame["high"] - data_frame["low"]
    data_frame["up_rod"] = np.where(data_frame["body"] > 0, data_frame["high"] - data_frame["close"], data_frame["high"] - data_frame["open"])
    data_frame["low_rod"] = np.where(data_frame["body"] > 0, data_frame["open"] - data_frame["low"], data_frame["close"] - data_frame["low"])
    data_frame["highlow"] = data_frame["high"] - data_frame["low"]
    data_frame["middle_price"] = pair.round_price((data_frame["inner_low"] + data_frame["inner_high"]) / 2)
    data_frame["middle_price_wick"] = pair.round_price((data_frame["high"] + data_frame["low"]) / 2)
    if "time" in data_frame.columns:
        data_frame = data_frame[[column for column in data_frame.columns if column != "time"] + ["time"]]
    return data_frame


def add_rsi(data_frame: pd.DataFrame, close_column: str = "close", period: int = 14, method: str = "wilder") -> pd.DataFrame:
    data_frame = data_frame.copy()
    delta = data_frame[close_column].diff()
    gain = delta.where(delta > 0, 0)
    loss = -delta.where(delta < 0, 0)
    if method == "wilder":
        average_gain = gain.ewm(alpha=1.0 / period, adjust=False).mean()
        average_loss = loss.ewm(alpha=1.0 / period, adjust=False).mean()
    else:
        average_gain = gain.ewm(span=period, adjust=False).mean()
        average_loss = loss.ewm(span=period, adjust=False).mean()
    data_frame["RSI"] = round(100 - (100 / (1 + average_gain / average_loss)), 1)
    return data_frame



def add_macd(data_frame: pd.DataFrame) -> pd.DataFrame:
    data_frame = data_frame.copy().sort_index(ascending=True)
    data_frame["macd_ema_s"] = data_frame["close"].ewm(span=12).mean()
    data_frame["macd_ema_l"] = data_frame["close"].ewm(span=26).mean()
    data_frame["macd"] = data_frame["macd_ema_s"] - data_frame["macd_ema_l"]
    data_frame["macd_signal"] = data_frame["macd"].ewm(span=9).mean()
    data_frame["macd_gap"] = data_frame["macd"] - data_frame["macd_signal"]
    data_frame["macd_bool"] = data_frame["macd"] > data_frame["macd_signal"]
    dead = (data_frame["macd_bool"] != data_frame["macd_bool"].shift(1)) & ~data_frame["macd_bool"]
    gold = (data_frame["macd_bool"] != data_frame["macd_bool"].shift(1)) & data_frame["macd_bool"]
    data_frame["macd_cross"] = [up + down * -1 for up, down in zip(gold, dead)]
    return data_frame


def add_ema_data(data_frame: pd.DataFrame) -> pd.DataFrame:
    data_frame = data_frame.copy()
    data_frame["ema_l"] = data_frame["close"].ewm(span=23).mean()
    data_frame["ema_s"] = data_frame["close"].ewm(span=2).mean()
    data_frame["ema_gap"] = data_frame["ema_s"] - data_frame["ema_l"]
    data_frame["ema_bool"] = data_frame["ema_s"] > data_frame["ema_l"]
    dead = (data_frame["ema_bool"] != data_frame["ema_bool"].shift(1)) & ~data_frame["ema_bool"]
    gold = (data_frame["ema_bool"] != data_frame["ema_bool"].shift(1)) & data_frame["ema_bool"]
    data_frame["cross"] = [up + down * -1 for up, down in zip(gold, dead)]
    data_frame["cross_price"] = data_frame["ema_s"].where(data_frame["cross"] != 0)
    data_frame["close_tilt"] = (data_frame["close"] - data_frame["close"].shift(2)) / 3
    data_frame["ema_l_tilt"] = (data_frame["ema_l"] - data_frame["ema_l"].shift(2)) / 3
    data_frame["ema_s_tilt"] = (data_frame["ema_s"] - data_frame["ema_s"].shift(2)) / 3
    data_frame["cross_tilt"] = data_frame.apply(_cross_angle, axis=1)
    return data_frame


def _cross_angle(row: pd.Series) -> float:
    first = np.array([row.ema_l_tilt, 1])
    second = np.array([row.ema_s_tilt, 1])
    cosine = np.inner(first, second) / (np.linalg.norm(first) * np.linalg.norm(second))
    angle = round(np.rad2deg(np.arccos(np.clip(cosine, -1.0, 1.0))), 1)
    return -angle if row.ema_l > row.ema_s else angle


def add_bb_data(data_frame: pd.DataFrame, pair=None) -> pd.DataFrame:
    pair = pair or currency_pair("USD_JPY")
    data_frame = data_frame.copy()
    mean = data_frame["close"].rolling(window=30).mean()
    standard_deviation = data_frame["close"].rolling(window=30).std()
    data_frame["bb_upper"] = mean + standard_deviation * 2
    data_frame["bb_lower"] = mean - standard_deviation * 2
    data_frame["bb_middle"] = pair.round_price((data_frame["bb_lower"] + data_frame["bb_upper"]) / 2)
    data_frame["bb_range"] = data_frame["bb_upper"] - data_frame["bb_lower"]
    return data_frame
