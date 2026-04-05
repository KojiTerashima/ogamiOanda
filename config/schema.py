from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


class SettingsValidationError(ValueError):
    """Raised when settings data is structurally invalid."""


@dataclass(frozen=True)
class OandaCredentials:
    account_id: str
    access_token: str
    environment: str


@dataclass(frozen=True)
class DiscordWebhookConfig:
    main: str
    sub: str


@dataclass(frozen=True)
class PathConfig:
    log: str
    csv: str
    folder: str
    history_folder: str
    setting_folder: str
    inspection_data_cache_folder: str


@dataclass(frozen=True)
class AppSettings:
    practice: OandaCredentials
    live: OandaCredentials
    live_sub_account_id: str
    discord: DiscordWebhookConfig
    paths: PathConfig

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "AppSettings":
        if not isinstance(raw, dict):
            raise SettingsValidationError("Settings root must be a mapping.")

        practice_data = _get_mapping(raw, "oanda.practice")
        live_data = _get_mapping(raw, "oanda.live")
        live_sub_data = _get_optional_mapping(raw, "oanda.live_sub")
        discord_data = _get_mapping(raw, "discord")
        paths_data = _get_mapping(raw, "paths")

        live_account_id = _get_str(live_data, "account_id", "oanda.live")
        live_sub_account_id = live_account_id
        if live_sub_data is not None and "account_id" in live_sub_data:
            live_sub_account_id = _get_str(
                live_sub_data,
                "account_id",
                "oanda.live_sub",
            )

        return cls(
            practice=OandaCredentials(
                account_id=_get_str(practice_data, "account_id", "oanda.practice"),
                access_token=_get_str(
                    practice_data,
                    "access_token",
                    "oanda.practice",
                ),
                environment=_get_str(practice_data, "environment", "oanda.practice"),
            ),
            live=OandaCredentials(
                account_id=live_account_id,
                access_token=_get_str(live_data, "access_token", "oanda.live"),
                environment=_get_str(live_data, "environment", "oanda.live"),
            ),
            live_sub_account_id=live_sub_account_id,
            discord=DiscordWebhookConfig(
                main=_get_str(discord_data, "webhook_main", "discord"),
                sub=_get_str(discord_data, "webhook_sub", "discord"),
            ),
            paths=PathConfig(
                log=_get_str(paths_data, "log", "paths"),
                csv=_get_str(paths_data, "csv", "paths"),
                folder=_get_str(paths_data, "folder", "paths"),
                history_folder=_get_str(paths_data, "history_folder", "paths"),
                setting_folder=_get_str(paths_data, "setting_folder", "paths"),
                inspection_data_cache_folder=_get_str(
                    paths_data,
                    "inspection_data_cache_folder",
                    "paths",
                ),
            ),
        )

    def resolved_paths(self, root: Path) -> PathConfig:
        """Return a copy of path settings resolved against project root."""
        return PathConfig(
            log=str((root / self.paths.log).resolve()),
            csv=str((root / self.paths.csv).resolve()) if self.paths.csv else "",
            folder=str((root / self.paths.folder).resolve()) + "/",
            history_folder=str((root / self.paths.history_folder).resolve()) + "/",
            setting_folder=(
                str((root / self.paths.setting_folder).resolve()) + "/"
                if self.paths.setting_folder
                else ""
            ),
            inspection_data_cache_folder=(
                str((root / self.paths.inspection_data_cache_folder).resolve()) + "/"
                if self.paths.inspection_data_cache_folder
                else ""
            ),
        )


def _get_mapping(root: dict[str, Any], dotted_key: str) -> dict[str, Any]:
    current: Any = root
    for key in dotted_key.split("."):
        if not isinstance(current, dict) or key not in current:
            raise SettingsValidationError(
                f"Missing required mapping '{dotted_key}' in settings.yaml."
            )
        current = current[key]
    if not isinstance(current, dict):
        raise SettingsValidationError(
            f"Expected '{dotted_key}' to be a mapping in settings.yaml."
        )
    return current


def _get_optional_mapping(root: dict[str, Any], dotted_key: str) -> dict[str, Any] | None:
    current: Any = root
    for key in dotted_key.split("."):
        if not isinstance(current, dict) or key not in current:
            return None
        current = current[key]
    if not isinstance(current, dict):
        raise SettingsValidationError(
            f"Expected '{dotted_key}' to be a mapping in settings.yaml."
        )
    return current


def _get_str(root: dict[str, Any], key: str, scope: str) -> str:
    if key not in root:
        raise SettingsValidationError(
            f"Missing required key '{scope}.{key}' in settings.yaml."
        )
    value = root[key]
    if not isinstance(value, str):
        raise SettingsValidationError(
            f"Expected '{scope}.{key}' to be a string in settings.yaml."
        )
    return value
