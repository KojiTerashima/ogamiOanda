from datetime import datetime

import pytest

from ogami_oanda.adapters.notifications.discord import DiscordNotifier
from ogami_oanda.infrastructure.config.models import NotificationSettings
from tests.fakes import FixedClock


class _Http:
    def __init__(self):
        self.calls = []

    def post(self, url, json):
        self.calls.append((url, json))


@pytest.mark.contract
def test_discord_notifier_routes_and_suppresses_third_duplicate():
    http = _Http()
    notifier = DiscordNotifier(NotificationSettings({"EUR_USD": "eur", "USD_JPY": "jpy"}, "inspection"), FixedClock(datetime(2026, 1, 2, 3, 4, 5)), http)

    notifier.send("EUR_USD order")
    notifier.send("inspection backtest")
    notifier.send("repeat")
    notifier.send("repeat")
    notifier.send("repeat")

    assert [call[0] for call in http.calls] == ["eur", "inspection", "jpy", "jpy"]
    assert http.calls[0][1]["content"] == "@everyone  EUR_USD order (01/02_03:04:05)"


@pytest.mark.contract
def test_discord_notifier_noops_without_webhook_and_truncates_long_message():
    http = _Http()
    notifier = DiscordNotifier(NotificationSettings(), FixedClock(datetime(2026, 1, 2)), http)
    notifier.send("USD_JPY no webhook")
    assert http.calls == []

    notifier = DiscordNotifier(NotificationSettings({"USD_JPY": "jpy"}), FixedClock(datetime(2026, 1, 2)), http)
    notifier.send("x" * 2000)
    assert "Discord受信許容文字数オーバー" in http.calls[0][1]["content"]
