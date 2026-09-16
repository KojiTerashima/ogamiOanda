from datetime import datetime
from types import ModuleType

import pytest
import requests

from ogami_oanda.adapters.notifications.discord import DiscordNotifier
from ogami_oanda.infrastructure.config.legacy_tokens import settings_from_tokens
from ogami_oanda.infrastructure.config.models import NotificationSettings
from tests.fakes import FixedClock


def _legacy_settings():
    tokens = ModuleType("tokens")
    tokens.WEBHOOK_URL_usdyen = "jpy"
    tokens.WEBHOOK_URL_eurousd = "eur"
    tokens.WEBHOOK_URL_inspection = "inspection"
    return settings_from_tokens(tokens).notifications


def _strategy_settings():
    return NotificationSettings(
        pair_webhooks={"USD_JPY": "legacy-jpy", "AUD_USD": "legacy-aud"},
        inspection_webhook="inspection",
        strategy_pair_webhooks={
            "original": {"USD_JPY": "jpy", "EUR_USD": "eur", "AUD_USD": ""},
            "matcha": {"USD_JPY": "matcha-jpy"},
        },
    )


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
    notifier = DiscordNotifier(_legacy_settings(), FixedClock(datetime(2026, 1, 2, 3, 4, 5)), http)

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

    notifier = DiscordNotifier(_strategy_settings(), FixedClock(datetime(2026, 1, 2)), http, strategy_name="original")
    notifier.send("x" * 2000, pair="USD_JPY")
    assert "Discord受信許容文字数オーバー" in http.calls[0][1]["content"]


@pytest.mark.contract
def test_discord_notifier_does_not_break_trading_on_transient_delivery_failure():
    notifier = DiscordNotifier(
        _strategy_settings(),
        FixedClock(datetime(2026, 1, 2)),
        _FailingHttp(),
        strategy_name="original",
    )

    notifier.send("USD_JPY order", pair="USD_JPY")

    requests_notifier = DiscordNotifier(
        _strategy_settings(),
        FixedClock(datetime(2026, 1, 2)),
        _RequestsFailingHttp(
            requests.exceptions.ConnectionError("webhook unavailable")
        ),
        strategy_name="original",
    )
    requests_notifier.send("USD_JPY order", pair="USD_JPY")

    status_notifier = DiscordNotifier(
        _strategy_settings(),
        FixedClock(datetime(2026, 1, 2)),
        _StatusFailingHttp(),
        strategy_name="original",
    )
    status_notifier.send("USD_JPY order", pair="USD_JPY")
    assert _StatusFailingHttp.checked is True


@pytest.mark.contract
def test_discord_notifier_keeps_unknown_programming_errors_fail_fast():
    notifier = DiscordNotifier(
        _strategy_settings(),
        FixedClock(datetime(2026, 1, 2)),
        _RequestsFailingHttp(RuntimeError("programming defect")),
        strategy_name="original",
    )

    with pytest.raises(RuntimeError, match="programming defect"):
        notifier.send("USD_JPY order", pair="USD_JPY")


@pytest.mark.contract
def test_strategy_and_pair_select_exact_routes_without_changing_content():
    http = _Http()
    clock = FixedClock(datetime(2026, 1, 2, 3, 4, 5))
    original = DiscordNotifier(_strategy_settings(), clock, http, strategy_name="original")
    matcha = DiscordNotifier(_strategy_settings(), clock, http, strategy_name="matcha")

    original.send("same order", pair="USD_JPY")
    original.send("same order", pair="EUR_USD")
    matcha.send("same order", pair="USD_JPY")

    assert [url for url, _ in http.calls] == ["jpy", "eur", "matcha-jpy"]
    assert all(payload == {
        "content": "@everyone  same order (01/02_03:04:05)",
        "allowed_mentions": {"parse": ["everyone"]},
    } for _, payload in http.calls)


@pytest.mark.contract
@pytest.mark.parametrize(("strategy", "pair"), [
    (None, "USD_JPY"), ("", "USD_JPY"), ("unknown", "USD_JPY"),
    ("matcha", "EUR_USD"), ("original", "AUD_USD"), ("original", "GBP_USD"),
    ("original", None), ("original", ""), ("Original", "USD_JPY"),
    ("original", "usd_jpy"),
])
def test_missing_route_never_falls_back_or_infers_pair_from_message(strategy, pair):
    http = _Http()
    notifier = DiscordNotifier(_strategy_settings(), FixedClock(datetime(2026, 1, 2)), http, strategy_name=strategy)
    notifier.send("USD_JPY order", pair=pair)
    assert http.calls == []


@pytest.mark.contract
def test_pair_only_settings_do_not_enable_legacy_routing():
    http = _Http()
    settings = NotificationSettings({"USD_JPY": "legacy-jpy"})
    notifier = DiscordNotifier(settings, FixedClock(datetime(2026, 1, 2)), http, strategy_name="original")
    notifier.send("USD_JPY order", pair="USD_JPY")
    assert http.calls == []


@pytest.mark.contract
@pytest.mark.parametrize("same_webhook", [False, True])
def test_duplicates_are_independent_per_route_and_reset_on_changed_message(same_webhook):
    http = _Http()
    settings = NotificationSettings(strategy_pair_webhooks={"original": {
        "USD_JPY": "jpy", "EUR_USD": "jpy" if same_webhook else "eur",
    }})
    notifier = DiscordNotifier(settings, FixedClock(datetime(2026, 1, 2)), http, strategy_name="original")
    for _ in range(3):
        notifier.send("same order", pair="USD_JPY")
        notifier.send("same order", pair="EUR_USD")
    assert len(http.calls) == 4
    notifier.send("changed", pair="USD_JPY")
    notifier.send("same order", pair="USD_JPY")
    notifier.send("same order", pair="EUR_USD")
    assert len(http.calls) == 6


@pytest.mark.contract
@pytest.mark.parametrize("strategy", [None, "original", "matcha", "unknown"])
@pytest.mark.parametrize(("message", "category"), [
    ("report", "inspection"), ("inspection result", "live"),
    ("backtest result", "live"), ("検証結果", "live"),
])
def test_inspection_remains_shared_even_without_a_normal_route(strategy, message, category):
    http = _Http()
    notifier = DiscordNotifier(_strategy_settings(), FixedClock(datetime(2026, 1, 2)), http, strategy_name=strategy)
    notifier.send(message, category=category)
    assert [url for url, _ in http.calls] == ["inspection"]


@pytest.mark.contract
@pytest.mark.parametrize("message", [
    "★★★オーダー発行 backtest", "■■■解消：検証", "■■■解消: inspection", "【inspection no order】",
])
def test_historical_live_notice_exceptions_still_use_normal_route(message):
    http = _Http()
    notifier = DiscordNotifier(_strategy_settings(), FixedClock(datetime(2026, 1, 2)), http, strategy_name="matcha")
    notifier.send(message, category="inspection", pair="USD_JPY")
    assert [url for url, _ in http.calls] == ["matcha-jpy"]


@pytest.mark.contract
def test_tokens_compatibility_takes_precedence_over_bound_strategy():
    http = _Http()
    notifier = DiscordNotifier(_legacy_settings(), FixedClock(datetime(2026, 1, 2)), http, strategy_name="original")
    notifier.send("EUR_USD order")
    notifier.send("same", pair="USD_JPY")
    notifier.send("same", pair="EUR_USD")
    notifier.send("same", pair="USD_JPY")
    assert [url for url, _ in http.calls] == ["eur", "jpy", "eur"]
