from __future__ import annotations

import os
from pathlib import Path
from typing import Mapping

import yaml

from .models import (
    AppSettings,
    NotificationSettings,
    PathSettings,
    RuntimeAccountConfig,
    TradingSettings,
)


def _environment_value(value: object, environment: Mapping[str, str]) -> str:
    if not isinstance(value, str):
        return str(value or "")
    if value.startswith("${") and value.endswith("}"):
        return environment.get(value[2:-1], "")
    return value


def load_settings(path: str | Path, environment: Mapping[str, str] | None = None) -> AppSettings:
    environment = os.environ if environment is None else environment
    with Path(path).open(encoding="utf-8") as settings_file:
        raw = yaml.safe_load(settings_file) or {}
    accounts = {
        name: RuntimeAccountConfig(
            account_id=_environment_value(values.get("account_id"), environment),
            access_token=_environment_value(values.get("access_token"), environment),
            environment=str(values.get("environment", "practice")),
        )
        for name, values in raw.get("accounts", {}).items()
    }
    trading_raw = raw.get("trading", {})
    notification_raw = raw.get("notifications", {})
    paths_raw = raw.get("paths", {})
    return AppSettings(
        accounts=accounts,
        trading=TradingSettings(
            default_pair=str(trading_raw.get("default_pair", "USD_JPY")),
            line_units=float(trading_raw.get("line_units", 1.0)),
            risk_yen=float(trading_raw.get("risk_yen", 500.0)),
            max_positions=int(trading_raw.get("max_positions", 15)),
            normal_slot_count=int(trading_raw.get("normal_slot_count", 6)),
            mid_slot_count=int(trading_raw.get("mid_slot_count", 8)),
            high_slot_count=int(trading_raw.get("high_slot_count", 1)),
            mid_priority_threshold=int(
                trading_raw.get("mid_priority_threshold", 10)
            ),
            high_priority_threshold=int(
                trading_raw.get("high_priority_threshold", 100)
            ),
        ),
        notifications=NotificationSettings(
            pair_webhooks={
                str(pair): _environment_value(url, environment)
                for pair, url in notification_raw.get("pair_webhooks", {}).items()
            },
            inspection_webhook=_environment_value(notification_raw.get("inspection_webhook", ""), environment),
        ),
        paths=PathSettings(
            result_dir=str(paths_raw.get("result_dir", ".")),
            cache_dir=str(paths_raw.get("cache_dir", ".")),
            history_file=str(paths_raw.get("history_file", "history.csv")),
        ),
    )
