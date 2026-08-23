from __future__ import annotations

import json
import os
import sys
import types
from functools import lru_cache
from pathlib import Path

import pandas as pd
import pytest

from ogami_oanda.domain.analysis.indicators import add_bb_data, add_rsi


def _install_tokens_stub() -> None:
    tokens = types.ModuleType("tokens")
    tokens.accountID = "test-practice-account"
    tokens.access_token = "test-practice-token"
    tokens.environment = "practice"
    tokens.accountIDl = "test-live-account"
    tokens.accountIDl2 = "test-live-account-2"
    tokens.access_tokenl = "test-live-token"
    tokens.environmentl = "practice"
    tokens.WEBHOOK_URL_usdyen = ""
    tokens.WEBHOOK_URL_eurousd = ""
    tokens.WEBHOOK_URL_inspection = ""
    tokens.WEBHOOK_URL_main = ""
    tokens.WEBHOOK_URL_friend = ""
    tokens.folder_path = "."
    tokens.setting_json = {"l_units": 500}
    sys.modules["tokens"] = tokens


_install_tokens_stub()


_ANALYSIS_FIXTURE_SPEC_PATH = Path(__file__).parent / "fixtures" / "analysis_frame_specs.json"


@lru_cache(maxsize=1)
def _analysis_frame_specs() -> dict[str, dict[str, dict[str, object]]]:
    return json.loads(_ANALYSIS_FIXTURE_SPEC_PATH.read_text(encoding="utf-8"))


def _pair_pip_value(pair_name: str) -> float:
    return 0.01 if pair_name == "USD_JPY" else 0.0001


def _pair_round_digits(pair_name: str) -> int:
    return 3 if pair_name == "USD_JPY" else 5


def _round_series(series: pd.Series, digits: int) -> pd.Series:
    return series.round(digits)


def _build_analysis_frame(pair_name: str, timeframe: str) -> pd.DataFrame:
    spec = _analysis_frame_specs()[pair_name][timeframe]
    digits = _pair_round_digits(pair_name)
    pip_value = _pair_pip_value(pair_name)
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
    frame["high"] = _round_series(frame[["open", "close"]].max(axis=1) + wick_pips * pip_value, digits)
    frame["low"] = _round_series(frame[["open", "close"]].min(axis=1) - wick_pips * pip_value, digits)
    frame["inner_high"] = _round_series(frame[["open", "close"]].max(axis=1), digits)
    frame["inner_low"] = _round_series(frame[["open", "close"]].min(axis=1), digits)
    frame["body"] = _round_series(frame["close"] - frame["open"], digits)
    frame["body_abs"] = _round_series(frame["body"].abs(), digits)
    frame["moves"] = _round_series(frame["high"] - frame["low"], digits)
    frame["highlow"] = frame["moves"]
    frame["mid_outer"] = _round_series((frame["high"] + frame["low"]) / 2, digits)
    frame["middle_price"] = _round_series((frame["inner_high"] + frame["inner_low"]) / 2, digits)
    frame["middle_price_wick"] = frame["mid_outer"]
    frame["up_rod"] = _round_series(frame["high"] - frame[["open", "close"]].max(axis=1), digits)
    frame["low_rod"] = _round_series(frame[["open", "close"]].min(axis=1) - frame["low"], digits)
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
        frame[column] = _round_series(frame[column], digits)
    return frame


@pytest.fixture(autouse=True)
def block_network(request, monkeypatch):
    integration_enabled = (
        request.node.get_closest_marker("integration") is not None
        and os.environ.get("OGAMI_OANDA_RUN_INTEGRATION") == "1"
    )
    if integration_enabled:
        return

    def fail_network(*args, **kwargs):
        raise AssertionError("Network access is prohibited in offline tests")

    monkeypatch.setattr("requests.sessions.Session.request", fail_network)


@pytest.fixture(scope="session")
def analysis_frame_store() -> dict[str, dict[str, pd.DataFrame]]:
    return {
        pair_name: {
            timeframe: _build_analysis_frame(pair_name, timeframe)
            for timeframe in timeframe_specs
        }
        for pair_name, timeframe_specs in _analysis_frame_specs().items()
    }


@pytest.fixture
def candle_frame() -> pd.DataFrame:
    times = pd.date_range("2026-01-02 00:25:00", periods=6, freq="-5min")
    close = [150.30, 150.20, 150.10, 150.00, 150.10, 150.20]
    return pd.DataFrame(
        {
            "time_jp": [time.strftime("%Y/%m/%d %H:%M:%S") for time in times],
            "time_jp_dt": times,
            "open": [150.25, 150.15, 150.05, 150.05, 150.15, 150.25],
            "close": close,
            "high": [price + 0.03 for price in close],
            "low": [price - 0.03 for price in close],
            "inner_high": [price + 0.01 for price in close],
            "inner_low": [price - 0.01 for price in close],
            "middle_price": close,
            "body_abs": [0.05] * 6,
            "moves": [0.06] * 6,
            "RSI": [55.0] * 6,
        }
    )
