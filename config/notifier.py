from __future__ import annotations

import datetime
from typing import Protocol, runtime_checkable

import requests


@runtime_checkable
class Notifier(Protocol):
    """Notification abstraction — implementations send messages to operators."""

    def notify(self, *args: object) -> None: ...


class NullNotifier:
    """No-op notifier used in tests and dry-run scenarios."""

    def notify(self, *args: object) -> None:
        pass


class DiscordNotifier:
    """Sends formatted messages to Discord webhooks."""

    def __init__(self, webhook_main: str, webhook_sub: str) -> None:
        self._webhook_main = webhook_main
        self._webhook_sub = webhook_sub

    def notify(self, *args: object) -> None:
        message = " ".join(str(a) for a in args)

        now_str = f"{datetime.datetime.now():%Y/%m/%d %H:%M:%S}"
        day_time = f" ({now_str[5:10]}_{now_str[11:19]})"
        message = message + day_time

        if len(message) >= 2000:
            print("@@文字オーバー")
            message = f"Discord受信許容文字数オーバー{len(message)}@{message[:50]}"

        data = {
            "content": "@everyone " + message,
            "allowed_mentions": {"parse": ["everyone"]},
        }
        requests.post(self._webhook_main, json=data)

        # 特定キーワードのみサブchに転送
        if any(
            kw in message
            for kw in ["■■■解消:", "★オーダー発行", "test from Webfook"]
        ):
            requests.post(self._webhook_sub, json={"content": message})

        print("     [Disc]", message)


_default: Notifier | None = None


def get_notifier() -> Notifier:
    """Return a module-level cached default Notifier built from YAML settings."""
    global _default
    if _default is None:
        from config.loader import load_settings  # lazy import

        settings = load_settings().settings
        _default = DiscordNotifier(settings.discord.main, settings.discord.sub)
    return _default
