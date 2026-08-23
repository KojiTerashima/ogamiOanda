from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

import pandas as pd

_ANALYSIS_FIXTURE_SPEC_PATH = Path(__file__).resolve().parent.parent / "fixtures" / "analysis_frame_specs.json"


def pair_round_digits(pair_name: str) -> int:
    return 3 if pair_name == "USD_JPY" else 5


def pair_pip_value(pair_name: str) -> float:
    return 0.01 if pair_name == "USD_JPY" else 0.0001


@lru_cache(maxsize=1)
def analysis_frame_specs() -> dict[str, dict[str, dict[str, object]]]:
    return json.loads(_ANALYSIS_FIXTURE_SPEC_PATH.read_text(encoding="utf-8"))


def build_candle_response(
    pair_name: str,
    timeframe: str,
    spec: dict[str, object] | None = None,
) -> dict[str, list[dict[str, object]]]:
    spec = spec or analysis_frame_specs()[pair_name][timeframe]
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

    candles = []
    for index, time in enumerate(times):
        open_price = open_prices[index]
        close_price = close_prices[index]
        high = round(max(open_price, close_price) + wick_pips * pip_value, digits)
        low = round(min(open_price, close_price) - wick_pips * pip_value, digits)
        utc_time = time.tz_localize("Asia/Tokyo").tz_convert("UTC")
        candles.append(
            {
                "time": utc_time.strftime("%Y-%m-%dT%H:%M:%S.000000000Z"),
                "mid": {
                    "o": str(open_price),
                    "c": str(close_price),
                    "h": str(high),
                    "l": str(low),
                },
                "volume": 100 + index,
                "complete": True,
            }
        )
    return {"candles": candles}


def response_to_legacy_frame(response: dict[str, object]) -> pd.DataFrame:
    return pd.DataFrame(response["candles"])


def build_response_store(
    pair_name: str,
    frame_specs: dict[str, dict[str, object]] | None = None,
) -> dict[str, dict[str, list[dict[str, object]]]]:
    specs = frame_specs or analysis_frame_specs()[pair_name]
    return {
        timeframe: build_candle_response(pair_name, timeframe, dict(spec))
        for timeframe, spec in specs.items()
    }


def build_frame_store(
    pair_name: str,
    frame_specs: dict[str, dict[str, object]] | None = None,
) -> dict[str, pd.DataFrame]:
    return {
        timeframe: response_to_legacy_frame(response)
        for timeframe, response in build_response_store(pair_name, frame_specs).items()
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
