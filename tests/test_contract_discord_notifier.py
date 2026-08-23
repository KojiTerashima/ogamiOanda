from datetime import datetime

import pytest
import requests

from ogami_oanda.adapters.notifications.discord import DiscordNotifier
from ogami_oanda.infrastructure.config.models import NotificationSettings
from tests.fakes import FixedClock


class _Http:
    def __init__(self):
        self.calls = []

    def post(self, url, json):
        self.calls.append((url, json))


class _FailingHttp:
    def post(self, url, json):
        del url, json
        raise ConnectionError("webhook unavailable")


class _RequestsFailingHttp:
    def __init__(self, error):
        self.error = error

    def post(self, url, json):
        del url, json
        raise self.error


class _StatusFailingHttp:
    checked = False

    class _Response:
        def raise_for_status(self):
            _StatusFailingHttp.checked = True
            raise requests.exceptions.HTTPError("Discord returned 503")

    def post(self, url, json):
        del url, json
        return self._Response()


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


@pytest.mark.contract
def test_discord_notifier_does_not_break_trading_on_transient_delivery_failure():
    notifier = DiscordNotifier(
        NotificationSettings({"USD_JPY": "jpy"}),
        FixedClock(datetime(2026, 1, 2)),
        _FailingHttp(),
    )

    notifier.send("USD_JPY order")

    requests_notifier = DiscordNotifier(
        NotificationSettings({"USD_JPY": "jpy"}),
        FixedClock(datetime(2026, 1, 2)),
        _RequestsFailingHttp(
            requests.exceptions.ConnectionError("webhook unavailable")
        ),
    )
    requests_notifier.send("USD_JPY order")

    status_notifier = DiscordNotifier(
        NotificationSettings({"USD_JPY": "jpy"}),
        FixedClock(datetime(2026, 1, 2)),
        _StatusFailingHttp(),
    )
    status_notifier.send("USD_JPY order")
    assert _StatusFailingHttp.checked is True


@pytest.mark.contract
def test_discord_notifier_keeps_unknown_programming_errors_fail_fast():
    notifier = DiscordNotifier(
        NotificationSettings({"USD_JPY": "jpy"}),
        FixedClock(datetime(2026, 1, 2)),
        _RequestsFailingHttp(RuntimeError("programming defect")),
    )

    with pytest.raises(RuntimeError, match="programming defect"):
        notifier.send("USD_JPY order")
