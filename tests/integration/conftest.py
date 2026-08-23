from __future__ import annotations

import os
from pathlib import Path

import pytest

from ogami_oanda.adapters.oanda.client import OandaClient
from ogami_oanda.infrastructure.config.loader import load_settings


@pytest.fixture(scope="session")
def practice_oanda_client():
    if os.environ.get("OGAMI_OANDA_RUN_INTEGRATION") != "1":
        pytest.skip("set OGAMI_OANDA_RUN_INTEGRATION=1 to enable integration tests")
    config_path = os.environ.get(
        "OGAMI_OANDA_INTEGRATION_CONFIG",
        "config/settings.yaml",
    )
    path = Path(config_path)
    if not path.exists():
        pytest.skip("practice integration config is not available")
    settings = load_settings(path)
    account_name = os.environ.get(
        "OGAMI_OANDA_INTEGRATION_ACCOUNT",
        "practice",
    )
    account = settings.account(account_name)
    if account.environment != "practice":
        pytest.fail("integration tests require an OANDA practice account")
    if not account.account_id or not account.access_token:
        pytest.skip("practice integration credentials are not configured")
    return OandaClient(account)
