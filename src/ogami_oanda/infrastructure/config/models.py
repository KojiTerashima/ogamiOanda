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


@dataclass(frozen=True)
class NotificationSettings:
    pair_webhooks: Mapping[str, str] = field(default_factory=dict)
    inspection_webhook: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "pair_webhooks", MappingProxyType(dict(self.pair_webhooks)))


@dataclass(frozen=True)
class PathSettings:
    result_dir: str = "."
    cache_dir: str = "."
    history_file: str = "history.csv"


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
