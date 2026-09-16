from __future__ import annotations

from typing import Mapping, Protocol

from ogami_oanda.application.ports.clock import Clock


class NotificationConfiguration(Protocol):
    pair_webhooks: Mapping[str, str]
    inspection_webhook: str
    strategy_pair_webhooks: Mapping[str, Mapping[str, str]]
    legacy_pair_routing: bool


def create_http_session():
    """Keep the requests dependency at the notification adapter boundary."""
    import requests

    return requests.Session()


class DiscordNotifier:
    def __init__(
        self, settings: NotificationConfiguration, clock: Clock, http_session,
        *, strategy_name: str | None = None,
    ) -> None:
        self.settings = settings
        self.clock = clock
        self.http_session = http_session
        self.strategy_name = strategy_name
        self._last_messages: dict[tuple[str, ...], tuple[str, int]] = {}

    def send(self, message: str, *, category: str = "live", pair: str | None = None) -> None:
        import requests

        webhook = self._webhook(message, category, pair)
        if self.settings.legacy_pair_routing:
            # Preserve global consecutive-message suppression for root scripts.
            route = ()
        else:
            if not webhook:
                return
            route = (self.strategy_name or "", pair or "", category, webhook)
        if self._is_duplicate(message, route):
            return
        if not webhook:
            return
        timestamp = self.clock.now().strftime("%m/%d_%H:%M:%S")
        content = f" {message} ({timestamp})"
        if len(content) >= 2000:
            content = f"Discord受信許容文字数オーバー{len(content)}@{content[:50]}"
        try:
            response = self.http_session.post(
                webhook,
                json={
                    "content": "@everyone " + content,
                    "allowed_mentions": {"parse": ["everyone"]},
                },
            )
            raise_for_status = getattr(response, "raise_for_status", None)
            if raise_for_status is not None:
                raise_for_status()
        except (TimeoutError, ConnectionError, requests.exceptions.RequestException):
            return

    def _is_duplicate(self, message: str, route: tuple[str, ...]) -> bool:
        last_message, count = self._last_messages.get(route, ("", 0))
        count = count + 1 if message == last_message else 1
        self._last_messages[route] = (message, count)
        return count > 2

    def _webhook(self, message: str, category: str, pair: str | None) -> str:
        inspection = category == "inspection" or any(value in message.lower() for value in ("inspection", "backtest", "検証"))
        live_notice = message.strip().startswith(("★★★オーダー発行", "■■■解消：", "■■■解消:")) or (message.strip().startswith("【") and " no order】" in message)
        if inspection and not live_notice:
            return self.settings.inspection_webhook
        if self.settings.legacy_pair_routing:
            selected_pair = pair or self._pair_from_message(message)
            return self.settings.pair_webhooks.get(selected_pair, "")
        if not self.strategy_name or not pair:
            return ""
        return self.settings.strategy_pair_webhooks.get(self.strategy_name, {}).get(pair, "")

    @staticmethod
    def _pair_from_message(message: str) -> str:
        for pair in ("AUD_USD", "EUR_USD", "USD_JPY"):
            if pair in message:
                return pair
        return "USD_JPY"
