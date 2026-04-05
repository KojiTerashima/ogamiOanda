from pathlib import Path

import pytest

from config.loader import (
    ENV_SETTINGS_PATH,
    SettingsFileNotFoundError,
    load_settings,
    resolve_settings_path,
)
from config.schema import SettingsValidationError


def _write_yaml(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")


def test_resolve_settings_path_prefers_default_file(tmp_path: Path, monkeypatch):
    default_file = tmp_path / "settings.yaml"
    _write_yaml(default_file, "oanda: {}")

    env_candidate = tmp_path / "custom.yaml"
    _write_yaml(env_candidate, "oanda: {}")
    monkeypatch.setenv(ENV_SETTINGS_PATH, str(env_candidate))

    resolved = resolve_settings_path(cwd=tmp_path)

    assert resolved == default_file


def test_load_settings_raises_for_missing_required_keys(tmp_path: Path):
    invalid = tmp_path / "settings.yaml"
    _write_yaml(invalid, "{}")

    with pytest.raises(SettingsValidationError):
        load_settings(path=invalid)


def test_load_settings_success(tmp_path: Path):
    valid = tmp_path / "settings.yaml"
    _write_yaml(
        valid,
        """
oanda:
  practice:
    account_id: "p-id"
    access_token: "p-token"
    environment: "practice"
  live:
    account_id: "l-id"
    access_token: "l-token"
    environment: "live"
discord:
  webhook_main: "https://example.com/main"
  webhook_sub: "https://example.com/sub"
paths:
  log: "log.txt"
  csv: ""
  folder: "oanda_logs/"
  history_folder: "oanda_logs/history/"
  setting_folder: ""
  inspection_data_cache_folder: ""
""".strip(),
    )

    loaded = load_settings(path=valid)

    assert loaded.settings.live.account_id == "l-id"
    assert loaded.settings.discord.main == "https://example.com/main"


def test_resolve_settings_path_raises_when_not_found(tmp_path: Path, monkeypatch):
    monkeypatch.delenv(ENV_SETTINGS_PATH, raising=False)

    with pytest.raises(SettingsFileNotFoundError):
        resolve_settings_path(cwd=tmp_path)
