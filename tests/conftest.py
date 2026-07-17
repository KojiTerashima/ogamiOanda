from __future__ import annotations

import sys
import types

import pandas as pd
import pytest


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
    tokens.setting_json = {"l_units": 1}
    sys.modules["tokens"] = tokens


_install_tokens_stub()


@pytest.fixture(autouse=True)
def block_network(monkeypatch):
    def fail_network(*args, **kwargs):
        raise AssertionError("Network access is prohibited in offline tests")

    monkeypatch.setattr("requests.sessions.Session.request", fail_network)


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
