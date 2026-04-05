from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from config.schema import AppSettings, SettingsValidationError

ENV_SETTINGS_PATH = "OGAMI_OANDA_SETTINGS_PATH"
DEFAULT_SETTINGS_FILE = "settings.yaml"


class SettingsFileNotFoundError(FileNotFoundError):
    """Raised when no configuration file can be located."""


@dataclass(frozen=True)
class LoadedSettings:
    settings: AppSettings
    settings_path: Path


def resolve_settings_path(cwd: Path | None = None) -> Path:
    """Resolve config search order: ./settings.yaml -> ENV_SETTINGS_PATH."""
    root = cwd or Path.cwd()
    default_path = root / DEFAULT_SETTINGS_FILE
    if default_path.exists():
        return default_path

    env_path = os.getenv(ENV_SETTINGS_PATH, "").strip()
    if env_path:
        expanded = Path(env_path).expanduser()
        return expanded if expanded.is_absolute() else (root / expanded)

    raise SettingsFileNotFoundError(
        "Configuration file not found. Create './settings.yaml' or set "
        f"{ENV_SETTINGS_PATH} to a valid YAML file path."
    )


def load_settings(path: Path | None = None) -> LoadedSettings:
    settings_path = path or resolve_settings_path()

    if not settings_path.exists():
        raise SettingsFileNotFoundError(
            f"Configuration file does not exist: '{settings_path}'."
        )

    try:
        raw = yaml.safe_load(settings_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise SettingsValidationError(
            f"Failed to parse YAML settings file '{settings_path}': {exc}"
        ) from exc

    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise SettingsValidationError(
            f"Settings file '{settings_path}' must contain a YAML mapping."
        )

    return LoadedSettings(settings=AppSettings.from_dict(_normalize_raw(raw)), settings_path=settings_path)


def _normalize_raw(raw: dict[str, Any]) -> dict[str, Any]:
    """Support legacy key aliases to make migration safer."""
    normalized = dict(raw)
    oanda = dict(normalized.get("oanda", {}))

    if "practice" not in oanda and any(
        key in normalized for key in ["accountID", "access_token", "environment"]
    ):
        oanda["practice"] = {
            "account_id": normalized.get("accountID", ""),
            "access_token": normalized.get("access_token", ""),
            "environment": normalized.get("environment", "practice"),
        }
    if "live" not in oanda and any(
        key in normalized for key in ["accountIDl", "access_tokenl", "environmentl"]
    ):
        oanda["live"] = {
            "account_id": normalized.get("accountIDl", ""),
            "access_token": normalized.get("access_tokenl", ""),
            "environment": normalized.get("environmentl", "live"),
        }
    if oanda:
        normalized["oanda"] = oanda

    if "discord" not in normalized and any(
        key in normalized for key in ["WEBHOOK_URL_main", "WEBHOOK_URL_sub"]
    ):
        normalized["discord"] = {
            "webhook_main": normalized.get("WEBHOOK_URL_main", ""),
            "webhook_sub": normalized.get("WEBHOOK_URL_sub", ""),
        }

    if "paths" not in normalized and any(
        key in normalized
        for key in [
            "path_log",
            "path_csv",
            "folder_path",
            "history_folder_path",
            "setting_folder_path",
            "inspection_data_cache_folder_path",
        ]
    ):
        normalized["paths"] = {
            "log": normalized.get("path_log", "log.txt"),
            "csv": normalized.get("path_csv", ""),
            "folder": normalized.get("folder_path", "oanda_logs/"),
            "history_folder": normalized.get(
                "history_folder_path", "oanda_logs/history/"
            ),
            "setting_folder": normalized.get("setting_folder_path", ""),
            "inspection_data_cache_folder": normalized.get(
                "inspection_data_cache_folder_path", ""
            ),
        }

    return normalized
