from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Mapping

from ogami_oanda.application.settings import TradingSettings


@dataclass(frozen=True)
class RuntimeAccountConfig:
    account_id: str
    access_token: str
    environment: str
    client_extensions_enabled: bool = False
    require_hedging: bool = True
    live_trading_enabled: bool = False


@dataclass(frozen=True)
class NotificationSettings:
    pair_webhooks: Mapping[str, str] = field(default_factory=dict)
    inspection_webhook: str = ""
    strategy_pair_webhooks: Mapping[str, Mapping[str, str]] = field(default_factory=dict)
    # Enabled only by the tokens compatibility adapter, never by YAML settings.
    legacy_pair_routing: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "pair_webhooks", MappingProxyType(dict(self.pair_webhooks)))
        object.__setattr__(self, "strategy_pair_webhooks", MappingProxyType({
            strategy: MappingProxyType(dict(webhooks))
            for strategy, webhooks in self.strategy_pair_webhooks.items()
        }))


@dataclass(frozen=True)
class PathSettings:
    result_dir: str = "."
    cache_dir: str = "."
    history_file: str = "history.csv"
    position_state_dir: str = ""
    log_dir: str = "runtime/logs"


@dataclass(frozen=True)
class AppSettings:
    accounts: Mapping[str, RuntimeAccountConfig]
    trading: TradingSettings = field(default_factory=TradingSettings)
    notifications: NotificationSettings = field(default_factory=NotificationSettings)
    paths: PathSettings = field(default_factory=PathSettings)

    def __post_init__(self) -> None:
        object.__setattr__(self, "accounts", MappingProxyType(dict(self.accounts)))

    def account(self, name: str) -> RuntimeAccountConfig:
        try:
            return self.accounts[name]
        except KeyError as error:
            raise ValueError(f"Unknown account configuration: {name}") from error
