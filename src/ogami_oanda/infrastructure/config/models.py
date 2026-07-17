from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Mapping


@dataclass(frozen=True)
class RuntimeAccountConfig:
    account_id: str
    access_token: str
    environment: str


@dataclass(frozen=True)
class TradingSettings:
    default_pair: str = "USD_JPY"
    line_units: float = 1.0
    risk_yen: float = 500.0
    max_positions: int = 15


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
