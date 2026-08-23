from datetime import datetime
from pathlib import Path
from types import ModuleType

import pytest

from ogami_oanda.application.ports.broker import BrokerExecutionPort, BrokerQueryPort
from ogami_oanda.application.ports.market_data import MarketDataPort
from ogami_oanda.domain.orders.models import BrokerOrderRequest, OrderType
from ogami_oanda.infrastructure.config.legacy_tokens import settings_from_tokens
from ogami_oanda.infrastructure.config.loader import load_settings
from ogami_oanda.infrastructure.config.models import (
  AppSettings,
  RuntimeAccountConfig,
)
from tests.fakes import (
    FakeBroker,
    FakeMarketData,
    FakeNotifier,
    FixedClock,
    InMemoryTradeHistoryRepository,
)


@pytest.mark.contract
def test_yaml_settings_resolve_environment_variables(tmp_path):
    settings_path = tmp_path / "settings.yaml"
    settings_path.write_text(
        """\
accounts:
  primary:
    account_id: ${OANDA_ACCOUNT_ID}
    access_token: ${OANDA_ACCESS_TOKEN}
    environment: practice
    client_extensions_enabled: true
    require_hedging: true
trading:
  default_pair: EUR_USD
  line_units: 1.5
  risk_yen: 750
  max_positions: 4
  normal_slot_count: 2
  mid_slot_count: 1
  high_slot_count: 1
  mid_priority_threshold: 20
  high_priority_threshold: 200
notifications:
  pair_webhooks:
    EUR_USD: ${EUR_WEBHOOK}
paths:
  result_dir: results
  cache_dir: cache
  position_state_dir: state
""",
        encoding="utf-8",
    )

    settings = load_settings(
        settings_path,
        {"OANDA_ACCOUNT_ID": "account", "OANDA_ACCESS_TOKEN": "token", "EUR_WEBHOOK": ""},
    )

    assert settings.account("primary").account_id == "account"
    assert settings.account("primary").client_extensions_enabled is True
    assert settings.account("primary").require_hedging is True
    assert settings.trading.default_pair == "EUR_USD"
    assert settings.trading.line_units == 1.5
    assert settings.trading.risk_yen == 750
    assert settings.trading.max_positions == 4
    assert settings.trading.normal_slot_count == 2
    assert settings.trading.mid_slot_count == 1
    assert settings.trading.high_slot_count == 1
    assert settings.trading.mid_priority_threshold == 20
    assert settings.trading.high_priority_threshold == 200
    assert settings.notifications.pair_webhooks["EUR_USD"] == ""
    assert settings.paths.cache_dir == "cache"
    assert settings.paths.position_state_dir == "state"


@pytest.mark.contract
def test_account_correlation_features_default_to_mt4_safe_values():
    account = RuntimeAccountConfig("id", "token", "practice")

    assert account.client_extensions_enabled is False
    assert account.require_hedging is True
    assert account.live_trading_enabled is False


@pytest.mark.contract
@pytest.mark.parametrize(
    ("yaml_text", "environment", "message"),
    [
        (
            """\
accounts:
  primary:
    account_id: ${ACCOUNT_ID}
    access_token: ${SECRET_TOKEN}
    environment: practice
""",
            {"ACCOUNT_ID": "", "SECRET_TOKEN": "super-secret-value"},
            "account_id",
        ),
        (
            """\
accounts:
  primary:
    account_id: id
    access_token: ${SECRET_TOKEN}
    environment: invalid
""",
            {"SECRET_TOKEN": "super-secret-value"},
            "environment",
        ),
        (
            """\
accounts:
  primary:
    account_id: id
    access_token: ${SECRET_TOKEN}
    environment: practice
trading:
  max_positions: 4
  normal_slot_count: 1
  mid_slot_count: 1
  high_slot_count: 1
""",
            {"SECRET_TOKEN": "super-secret-value"},
            "slot counts",
        ),
        (
            """\
accounts:
  primary:
    account_id: id
    access_token: ${SECRET_TOKEN}
    environment: practice
trading:
  default_pair: GBP_USD
""",
            {"SECRET_TOKEN": "super-secret-value"},
            "default_pair",
        ),
    ],
)
def test_settings_validation_fails_closed_without_leaking_secrets(
    tmp_path,
    yaml_text,
    environment,
    message,
):
    path = tmp_path / "settings.yaml"
    path.write_text(yaml_text, encoding="utf-8")

    with pytest.raises(ValueError, match=message) as error_info:
        load_settings(path, environment)

    assert "super-secret-value" not in str(error_info.value)


@pytest.mark.contract
def test_live_account_requires_explicit_trading_opt_in():
    account = RuntimeAccountConfig("id", "token", "live")
    settings = AppSettings({"primary": account})

    assert settings.account("primary").live_trading_enabled is False


@pytest.mark.contract
def test_tracked_example_config_is_secret_free_and_loadable():
    path = Path(__file__).parents[1] / "config" / "settings.example.yaml"

    settings = load_settings(
        path,
        {
            "OANDA_PRACTICE_ACCOUNT_ID": "practice-id",
            "OANDA_PRACTICE_ACCESS_TOKEN": "practice-token",
        },
    )

    account = settings.account("practice")
    assert account.environment == "practice"
    assert account.client_extensions_enabled is False
    assert account.live_trading_enabled is False
    assert settings.paths.position_state_dir == "runtime/position-state"
    source = path.read_text(encoding="utf-8")
    assert "practice-token" not in source


@pytest.mark.contract
def test_tokens_compatibility_loader_keeps_secrets_in_memory_only():
    tokens = ModuleType("tokens")
    tokens.accountID = "practice-id"
    tokens.access_token = "practice-token"
    tokens.environment = "practice"
    tokens.accountIDl = "primary-id"
    tokens.accountIDl2 = "secondary-id"
    tokens.access_tokenl = "live-token"
    tokens.environmentl = "live"
    tokens.setting_json = {"l_units": 2}
    tokens.folder_path = "results"

    settings = settings_from_tokens(tokens)

    assert settings.account("primary").account_id == "primary-id"
    assert settings.account("secondary").access_token == "live-token"
    assert settings.trading.risk_yen == 2
    assert settings.paths.result_dir == "results"


@pytest.mark.contract
def test_offline_fakes_satisfy_port_contracts(candle_frame):
    market_data = FakeMarketData({("USD_JPY", "M5"): candle_frame}, {"USD_JPY": 150.3})
    broker = FakeBroker()
    request = BrokerOrderRequest("USD_JPY", 1000, OrderType.MARKET, 150.3, 150.5, 150.1)

    assert isinstance(market_data, MarketDataPort)
    assert isinstance(broker, BrokerExecutionPort)
    assert isinstance(broker, BrokerQueryPort)
    assert len(market_data.candles("USD_JPY", "M5", 2)) == 2
    assert market_data.current_price("USD_JPY") == 150.3
    assert broker.submit(request).reference_id == "order-1"

    notifier = FakeNotifier()
    notifier.send("offline", pair="USD_JPY")
    history = InMemoryTradeHistoryRepository()
    history.append({"result": "tp"})
    clock = FixedClock(datetime(2026, 1, 2, 3, 4, 5))
    assert notifier.messages == [("offline", "live", "USD_JPY")]
    assert history.records == [{"result": "tp"}]
    assert clock.now() == datetime(2026, 1, 2, 3, 4, 5)
