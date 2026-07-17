import datetime

import requests
import tokens as tk

import fGeneric as gene
from ogami_oanda.adapters.legacy.token_settings import settings_from_tokens
from ogami_oanda.adapters.notifications.discord import DiscordNotifier

line_send_last_message = ""
line_send_last_message_count = 0
LINE_SEND_DUPLICATE_LIMIT = 2


def is_live_notice_message(message):
    stripped = message.strip()
    return (
        stripped.startswith("★★★オーダー発行") or
        stripped.startswith("■■■解消：") or
        stripped.startswith("■■■解消:") or
        (stripped.startswith("【") and " no order】" in stripped)
    )


def is_inspection_notice_message(message):
    lower_message = message.lower()
    return (
        "inspection" in lower_message or
        "backtest" in lower_message or
        "検証" in message
    )


def notice_pair(message=""):
    if "AUD_USD" in message:
        return "AUD_USD"
    if "EUR_USD" in message:
        return "EUR_USD"
    if "USD_JPY" in message:
        return "USD_JPY"
    return getattr(gene.currentPair, "name", "USD_JPY")


def webhook_url_for_pair(pair):
    if pair == "AUD_USD":
        return getattr(tk, "WEBHOOK_URL_audusd", "")
    if pair == "EUR_USD":
        return getattr(tk, "WEBHOOK_URL_eurousd", getattr(tk, "WEBHOOK_URL_friend", ""))
    return getattr(tk, "WEBHOOK_URL_usdyen", getattr(tk, "WEBHOOK_URL_main", ""))


def line_send(*msg):
    global line_send_last_message, line_send_last_message_count

    message = ""
    for item in msg:
        message = message + " " + str(item)
    raw_message = message

    if raw_message == line_send_last_message:
        line_send_last_message_count += 1
    else:
        line_send_last_message = raw_message
        line_send_last_message_count = 1

    if line_send_last_message_count > LINE_SEND_DUPLICATE_LIMIT:
        print("     [Disc skip duplicate]", raw_message)
        return 0

    category = "inspection" if is_inspection_notice_message(raw_message) and not is_live_notice_message(raw_message) else "live"
    notifier = DiscordNotifier(settings_from_tokens(tk).notifications, _LegacyClock(), requests)
    notifier.send(raw_message.lstrip(), category=category, pair=notice_pair(raw_message))


class _LegacyClock:
    def now(self):
        return datetime.datetime.now()
