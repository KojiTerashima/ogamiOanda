from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

import pandas as pd

from ogami_oanda.domain.analysis.indicators import add_bb_data, add_rsi

_ANALYSIS_FIXTURE_SPEC_PATH = Path(__file__).resolve().parent.parent / "fixtures" / "analysis_frame_specs.json"


def pair_round_digits(pair_name: str) -> int:
    return 3 if pair_name == "USD_JPY" else 5


def pair_pip_value(pair_name: str) -> float:
    return 0.01 if pair_name == "USD_JPY" else 0.0001


@lru_cache(maxsize=1)
def analysis_frame_specs() -> dict[str, dict[str, dict[str, object]]]:
    return json.loads(_ANALYSIS_FIXTURE_SPEC_PATH.read_text(encoding="utf-8"))


def build_analysis_frame(pair_name: str, timeframe: str) -> pd.DataFrame:
    spec = analysis_frame_specs()[pair_name][timeframe]
    digits = pair_round_digits(pair_name)
    pip_value = pair_pip_value(pair_name)
    times = pd.date_range(
        end=pd.Timestamp(spec["latest_time"]),
        periods=int(spec["periods"]),
        freq=str(spec["frequency"]),
    )
    step_pips = [float(value) for value in spec["step_pips"]]
    body_pips = [float(value) for value in spec["body_pips"]]
    wick_pips = float(spec["wick_pips"])
    close_prices: list[float] = []
    open_prices: list[float] = []
    current_price = float(spec["base_price"])

    for index in range(len(times)):
        current_price += step_pips[index % len(step_pips)] * pip_value
        close_price = round(current_price, digits)
        body_price = body_pips[index % len(body_pips)] * pip_value
        open_price = round(close_price - body_price, digits)
        close_prices.append(close_price)
        open_prices.append(open_price)

    frame = pd.DataFrame(
        {
            "time_jp_dt": times,
            "time_jp": [time.strftime("%Y/%m/%d %H:%M:%S") for time in times],
            "open": open_prices,
            "close": close_prices,
        }
    )
    frame["high"] = (frame[["open", "close"]].max(axis=1) + wick_pips * pip_value).round(digits)
    frame["low"] = (frame[["open", "close"]].min(axis=1) - wick_pips * pip_value).round(digits)
    frame["inner_high"] = frame[["open", "close"]].max(axis=1).round(digits)
    frame["inner_low"] = frame[["open", "close"]].min(axis=1).round(digits)
    frame["body"] = (frame["close"] - frame["open"]).round(digits)
    frame["body_abs"] = frame["body"].abs().round(digits)
    frame["moves"] = (frame["high"] - frame["low"]).round(digits)
    frame["highlow"] = frame["moves"]
    frame["mid_outer"] = ((frame["high"] + frame["low"]) / 2).round(digits)
    frame["middle_price"] = ((frame["inner_high"] + frame["inner_low"]) / 2).round(digits)
    frame["middle_price_wick"] = frame["mid_outer"]
    frame["up_rod"] = (frame["high"] - frame[["open", "close"]].max(axis=1)).round(digits)
    frame["low_rod"] = (frame[["open", "close"]].min(axis=1) - frame["low"]).round(digits)
    frame = add_rsi(frame)
    frame = add_bb_data(frame)
    frame = frame.iloc[::-1].reset_index(drop=True)
    frame["time_jp_dt"] = pd.to_datetime(frame["time_jp_dt"])

    numeric_columns = [
        "open",
        "close",
        "high",
        "low",
        "inner_high",
        "inner_low",
        "body",
        "body_abs",
        "moves",
        "highlow",
        "mid_outer",
        "middle_price",
        "middle_price_wick",
        "up_rod",
        "low_rod",
        "bb_upper",
        "bb_lower",
        "bb_middle",
        "bb_range",
    ]
    for column in numeric_columns:
        frame[column] = frame[column].round(digits)
    return frame


def build_frame_store(pair_name: str) -> dict[str, pd.DataFrame]:
    return {
        timeframe: build_analysis_frame(pair_name, timeframe)
        for timeframe in analysis_frame_specs()[pair_name]
    }


def build_legacy_parity_frame_store(pair_name: str) -> dict[str, pd.DataFrame]:
    return {
        "M5": _generate_legacy_parity_frame(pair_name, periods=180, freq="5min"),
        "H1": _generate_legacy_parity_frame(pair_name, periods=120, freq="1h"),
        "M30": _generate_legacy_parity_frame(pair_name, periods=140, freq="30min"),
        "S5": _generate_legacy_parity_frame(pair_name, periods=120, freq="5s"),
    }


def _generate_legacy_parity_frame(pair_name: str, *, periods: int, freq: str) -> pd.DataFrame:
    is_jpy = pair_name.endswith("JPY")
    pip = 0.01 if is_jpy else 0.0001
    digits = pair_round_digits(pair_name)
    base = 149.8 if is_jpy else 1.1

    times = pd.date_range(end=pd.Timestamp("2026-01-02 12:00:00"), periods=periods, freq=freq)
    rows: list[dict[str, float | int | str]] = []
    for i, ts in enumerate(times):
        drift = ((i % 16) - 8) * pip
        close = round(base + drift, digits)
        open_price = round(close - ((i % 4) - 1) * pip, digits)
        high = round(max(open_price, close) + 2 * pip, digits)
        low = round(min(open_price, close) - 2 * pip, digits)
        inner_high = round(max(open_price, close), digits)
        inner_low = round(min(open_price, close), digits)
        body = round(close - open_price, digits)
        move = round(high - low, digits)
        rows.append(
            {
                "time_jp": ts.strftime("%Y/%m/%d %H:%M:%S"),
                "open": open_price,
                "close": close,
                "high": high,
                "low": low,
                "inner_high": inner_high,
                "inner_low": inner_low,
                "middle_price": round((inner_high + inner_low) / 2, digits),
                "middle_price_wick": round((high + low) / 2, digits),
                "mid_outer": round((high + low) / 2, digits),
                "body": body,
                "body_abs": abs(body),
                "direction": 1 if body > 0 else -1 if body < 0 else 0,
                "moves": move,
                "highlow": move,
                "up_rod": round(high - inner_high, digits),
                "low_rod": round(inner_low - low, digits),
                "RSI": float(40 + (i % 30)),
            }
        )

    frame = pd.DataFrame(rows).iloc[::-1].reset_index(drop=True)
    close_series = frame["close"]
    mean = close_series.rolling(window=30).mean()
    std = close_series.rolling(window=30).std()
    frame["bb_upper"] = mean + std * 2
    frame["bb_lower"] = mean - std * 2
    frame["bb_middle"] = ((frame["bb_lower"] + frame["bb_upper"]) / 2).round(digits)
    frame["bb_range"] = frame["bb_upper"] - frame["bb_lower"]
    return frame
