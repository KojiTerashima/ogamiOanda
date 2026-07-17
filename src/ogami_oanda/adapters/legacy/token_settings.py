from __future__ import annotations

from types import ModuleType

from ogami_oanda.infrastructure.config.models import (
    AppSettings,
    NotificationSettings,
    PathSettings,
    RuntimeAccountConfig,
    TradingSettings,
)


def settings_from_tokens(tokens: ModuleType) -> AppSettings:
    setting_json = getattr(tokens, "setting_json", {})
    return AppSettings(
        accounts={
            "practice": RuntimeAccountConfig(
                account_id=getattr(tokens, "accountID", ""),
                access_token=getattr(tokens, "access_token", ""),
                environment=getattr(tokens, "environment", "practice"),
            ),
            "primary": RuntimeAccountConfig(
                account_id=getattr(tokens, "accountIDl", ""),
                access_token=getattr(tokens, "access_tokenl", ""),
                environment=getattr(tokens, "environmentl", "practice"),
            ),
            "secondary": RuntimeAccountConfig(
                account_id=getattr(tokens, "accountIDl2", ""),
                access_token=getattr(tokens, "access_tokenl", ""),
                environment=getattr(tokens, "environmentl", "practice"),
            ),
        },
        trading=TradingSettings(line_units=float(setting_json.get("l_units", 1.0))),
        notifications=NotificationSettings(
            pair_webhooks={
                "USD_JPY": getattr(tokens, "WEBHOOK_URL_usdyen", ""),
                "EUR_USD": getattr(tokens, "WEBHOOK_URL_eurousd", ""),
                "AUD_USD": getattr(tokens, "WEBHOOK_URL_audusd", ""),
            },
            inspection_webhook=getattr(tokens, "WEBHOOK_URL_inspection", ""),
        ),
        paths=PathSettings(
            result_dir=getattr(tokens, "folder_path", "."),
            cache_dir=getattr(tokens, "inspection_data_cache_folder_path", "."),
            history_file=getattr(tokens, "history_folder_path", "") + "history.csv",
        ),
    )