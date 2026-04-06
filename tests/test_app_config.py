from pathlib import Path

from config.app_config import load_app_config


def test_load_app_config(tmp_path: Path, monkeypatch):
    settings_file = tmp_path / "settings.yaml"
    settings_file.write_text(
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
  folder: "oanda_logs"
  history_folder: "oanda_logs/history"
  setting_folder: ""
  inspection_data_cache_folder: ""
""".strip(),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    app_config = load_app_config()

    assert app_config.runtime_accounts.live_account_id == "l-id"
    assert app_config.runtime_accounts.live_sub_account_id == "l-id"
    assert app_config.folder_path == "oanda_logs/"
    assert app_config.history_folder_path == "oanda_logs/history/"
