from unittest.mock import MagicMock

from config.notifier import DiscordNotifier, Notifier, NullNotifier


def test_null_notifier_is_no_op():
    n = NullNotifier()
    n.notify("test", "message")  # should not raise


def test_null_notifier_satisfies_protocol():
    n = NullNotifier()
    assert isinstance(n, Notifier)


def test_discord_notifier_satisfies_protocol():
    n = DiscordNotifier("https://example.com/main", "https://example.com/sub")
    assert isinstance(n, Notifier)


def test_discord_notifier_posts_to_main_webhook(monkeypatch):
    posted = []

    def fake_post(url, json):
        posted.append((url, json))

    monkeypatch.setattr("config.notifier.requests.post", fake_post)

    n = DiscordNotifier("https://example.com/main", "https://example.com/sub")
    n.notify("テスト通知")

    assert len(posted) >= 1
    assert posted[0][0] == "https://example.com/main"
    assert "テスト通知" in posted[0][1]["content"]


def test_discord_notifier_forwards_keyword_to_sub_webhook(monkeypatch):
    posted = []

    def fake_post(url, json):
        posted.append((url, json))

    monkeypatch.setattr("config.notifier.requests.post", fake_post)

    n = DiscordNotifier("https://example.com/main", "https://example.com/sub")
    n.notify("■■■解消: ポジション解消")

    urls = [p[0] for p in posted]
    assert "https://example.com/sub" in urls


def test_discord_notifier_truncates_long_message(monkeypatch, capsys):
    monkeypatch.setattr("config.notifier.requests.post", MagicMock())

    n = DiscordNotifier("https://example.com/main", "https://example.com/sub")
    n.notify("x" * 3000)

    captured = capsys.readouterr()
    assert "@@文字オーバー" in captured.out
