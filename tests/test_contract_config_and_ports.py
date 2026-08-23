from datetime import datetime
from types import ModuleType

import pytest

from ogami_oanda.application.ports.broker import BrokerExecutionPort, BrokerQueryPort
from ogami_oanda.application.ports.market_data import MarketDataPort
from ogami_oanda.domain.orders.models import BrokerOrderRequest, OrderType
from ogami_oanda.infrastructure.config.legacy_tokens import settings_from_tokens
from ogami_oanda.infrastructure.config.loader import load_settings
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


@pytest.mark.contract
def test_account_correlation_features_default_to_mt4_safe_values():
    from ogami_oanda.infrastructure.config.models import RuntimeAccountConfig

    account = RuntimeAccountConfig("id", "token", "practice")

    assert account.client_extensions_enabled is False
    assert account.require_hedging is True


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
