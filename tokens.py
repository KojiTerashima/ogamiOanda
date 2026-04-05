import datetime  # 時刻の取得用
from pathlib import Path

import pandas as pd
import requests  # Line送信用

from config.loader import (
    DEFAULT_SETTINGS_FILE,
    ENV_SETTINGS_PATH,
    SettingsFileNotFoundError,
    load_settings,
)
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

# DiscordURL
WEBHOOK_URL_main = _settings.discord.main
WEBHOOK_URL_sub = _settings.discord.sub


def line_send(*msg):
    # 関数は可変複数のコンマ区切りの引数を受け付ける
    message = ""
    # 複数の引数を一つにする（数字が含まれる場合があるため、STRで文字化しておく）
    for item in msg:
        message = message + " " + str(item)
    # 時刻の表示を作成する
    now_str = f"{datetime.datetime.now():%Y/%m/%d %H:%M:%S}"
    day = now_str[5:10]  # 01/01
    time = now_str[11:19]  # 09:10
    day_time = " (" + day + "_" + time + ")"
    # メッセージの最後尾に付ける
    message = message + day_time

    if len(message) >= 2000:
        print("@@文字オーバー")
        message = (
            "Discord受信許容文字数オーバー" + str(len(message)) + "@" + message[:50]
        )

    # ■■■  通常のDiscord送信　■■■　　最悪これ以下だけあればいい
    WEBHOOK_URL = WEBHOOK_URL_main
    data = {
        "content": "@everyone " + message,
        "allowed_mentions": {"parse": ["everyone"]},
    }
    requests.post(WEBHOOK_URL, json=data)

    # ■Discord2 共有サーバーに送付(テストなので25/8には消去)
    line_to_friend(
        message
    )  # オプション（オーダーと結果のみを送信する。人に送りたくなければなくて負い）

    # ■コマンドラインに表示
    print("     [Disc]", message)  # コマンドラインにも表示


def line_to_friend(meg):
    """
    メッセージを受け取り、内容によって共有のDiscordに通知を送信する
    """
    if "■■■解消:" in meg or "★オーダー発行" in meg or "test from Webfook" in meg:
        # 指定の文字を含む場合のみ、送信
        WEBHOOK_URL = WEBHOOK_URL_sub
        data = {"content": meg}
        requests.post(WEBHOOK_URL, json=data)
    else:
        pass


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
