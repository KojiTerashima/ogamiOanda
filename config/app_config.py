from __future__ import annotations

from dataclasses import dataclass

from config.loader import load_settings
from config.runtime_accounts import RuntimeAccountConfig


@dataclass(frozen=True)
class AppConfig:
    runtime_accounts: RuntimeAccountConfig
    folder_path: str
    history_folder_path: str


def load_app_config() -> AppConfig:
    loaded = load_settings()
    settings = loaded.settings

    folder_path = _ensure_trailing_slash(settings.paths.folder)
    history_folder_path = _ensure_trailing_slash(settings.paths.history_folder)

    return AppConfig(
        runtime_accounts=RuntimeAccountConfig(
            practice_account_id=settings.practice.account_id,
            practice_access_token=settings.practice.access_token,
            practice_environment=settings.practice.environment,
            live_account_id=settings.live.account_id,
            live_sub_account_id=settings.live_sub_account_id,
            live_access_token=settings.live.access_token,
            live_environment=settings.live.environment,
            history_folder_path=history_folder_path,
        ),
        folder_path=folder_path,
        history_folder_path=history_folder_path,
    )


def _ensure_trailing_slash(path: str) -> str:
    if not path:
        return ""
    return path if path.endswith("/") else f"{path}/"
