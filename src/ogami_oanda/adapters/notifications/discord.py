from __future__ import annotations

from typing import Mapping, Protocol

from ogami_oanda.application.ports.clock import Clock


class NotificationConfiguration(Protocol):
    pair_webhooks: Mapping[str, str]
    inspection_webhook: str


def create_http_session():
    """Keep the requests dependency at the notification adapter boundary."""
    import requests

    return requests.Session()


class DiscordNotifier:
    def __init__(self, settings: NotificationConfiguration, clock: Clock, http_session) -> None:
        self.settings = settings
        self.clock = clock
        self.http_session = http_session
        self._last_message = ""
        self._duplicate_count = 0

    def send(self, message: str, *, category: str = "live", pair: str | None = None) -> None:
        if message == self._last_message:
            self._duplicate_count += 1
        else:
            self._last_message = message
            self._duplicate_count = 1
        if self._duplicate_count > 2:
            return
        webhook = self._webhook(message, category, pair)
        if not webhook:
            return
        timestamp = self.clock.now().strftime("%m/%d_%H:%M:%S")
        content = f" {message} ({timestamp})"
        if len(content) >= 2000:
            content = f"Discord受信許容文字数オーバー{len(content)}@{content[:50]}"
        self.http_session.post(webhook, json={"content": "@everyone " + content, "allowed_mentions": {"parse": ["everyone"]}})

    def _webhook(self, message: str, category: str, pair: str | None) -> str:
        inspection = category == "inspection" or any(value in message.lower() for value in ("inspection", "backtest", "検証"))
        live_notice = message.strip().startswith(("★★★オーダー発行", "■■■解消：", "■■■解消:")) or (message.strip().startswith("【") and " no order】" in message)
        if inspection and not live_notice:
            return self.settings.inspection_webhook
        selected_pair = pair or self._pair_from_message(message)
        return self.settings.pair_webhooks.get(selected_pair, "")

    @staticmethod
    def _pair_from_message(message: str) -> str:
        for pair in ("AUD_USD", "EUR_USD", "USD_JPY"):
            if pair in message:
                return pair
        return "USD_JPY"
