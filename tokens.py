import datetime  # 時刻の取得用
from pathlib import Path

import pandas as pd

from config.loader import (
    DEFAULT_SETTINGS_FILE,
    ENV_SETTINGS_PATH,
    SettingsFileNotFoundError,
    load_settings,
)
from config.notifier import DiscordNotifier as _DiscordNotifier
from config.schema import SettingsValidationError

try:
    _loaded = load_settings()
except (SettingsFileNotFoundError, SettingsValidationError) as exc:
    raise RuntimeError(
        "Failed to load configuration from YAML. "
        f"Create './{DEFAULT_SETTINGS_FILE}' or set '{ENV_SETTINGS_PATH}'. "
        "Copy from 'settings.example.yaml' and fill your own secrets. "
        f"Details: {exc}"
    ) from exc


_settings = _loaded.settings

# 練習環境
accountID = _settings.practice.account_id
access_token = _settings.practice.access_token
environment = _settings.practice.environment

# 本番環境
accountIDl = _settings.live.account_id
access_tokenl = _settings.live.access_token
environmentl = _settings.live.environment

# DiscordURL (後方互換のため公開変数として維持)
WEBHOOK_URL_main = _settings.discord.main
WEBHOOK_URL_sub = _settings.discord.sub

# 通知はDiscordNotifierに委譲
_notifier = _DiscordNotifier(WEBHOOK_URL_main, WEBHOOK_URL_sub)


def line_send(*msg):
    """後方互換の通知ラッパー。内部では DiscordNotifier.notify を呼び出す。"""
    _notifier.notify(*msg)


def line_to_friend(meg):
    """後方互換ラッパー。現在は line_send / DiscordNotifier 内で処理済み。"""
    pass  # サブch転送は DiscordNotifier.notify 内で実施


def f_write(path, msg):
    f = open(path, "r", encoding="Shift-JIS")
    f_data = f.read()
    f_data = (
        '{"date":'
        + str(datetime.datetime.now().replace(microsecond=0))
        + ","
        + msg
        + f_data
        + "\n"
    )  # 最後に改行する
    f = open(path, "w", encoding="Shift-JIS")
    f.write(f_data)
    f.close()


def write_result(dic):
    new_data = pd.DataFrame([dic])

    try:
        # CSVに追記（ヘッダーの重複を避けるため `mode="a"` で書き込み）
        new_data.to_csv(
            folder_path + "main_result.csv", mode="a", index=False, encoding="utf-8"
        )
    except Exception:
        print("結果書き込みエラーあり")


# ログ用ファイル設定
path_log = _settings.paths.log

# 結果核のようようCSVファイル
path_csv = _settings.paths.csv

# ログフォルダ設定
folder_path = _settings.paths.folder
history_folder_path = _settings.paths.history_folder  # spread sheet

# 読み込み設定ファイル（条件を途中で変えられるように）
setting_folder_path = _settings.paths.setting_folder

# 検討フォルダ用
inspection_data_cache_folder_path = _settings.paths.inspection_data_cache_folder


def _ensure_dirs() -> None:
    """Create known output directories to keep runtime behavior stable."""
    for candidate in [folder_path, history_folder_path]:
        if candidate:
            Path(candidate).mkdir(parents=True, exist_ok=True)


_ensure_dirs()
