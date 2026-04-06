from config.app_config import AppConfig
from config.dependency_container import DependencyContainer
from config.runtime_accounts import RuntimeAccountConfig


class _FakeNotifier:
    def __init__(self):
        self.messages = []

    def notify(self, *args):
        self.messages.append(args)


def _build_app_config() -> AppConfig:
    runtime_accounts = RuntimeAccountConfig(
        practice_account_id="p-id",
        practice_access_token="p-token",
        practice_environment="practice",
        live_account_id="l-id",
        live_sub_account_id="l2-id",
        live_access_token="l-token",
        live_environment="live",
        history_folder_path="oanda_logs/history/",
    )
    return AppConfig(
        runtime_accounts=runtime_accounts,
        folder_path="oanda_logs/",
        history_folder_path="oanda_logs/history/",
    )


def test_container_creates_dependencies_from_factories():
    called = {
        "oanda": None,
        "position": None,
        "candle": None,
    }

    fake_notifier = _FakeNotifier()

    def fake_oanda(*args):
        called["oanda"] = args
        return {"kind": "oanda", "args": args}

    def fake_position_control(*args, **kwargs):
        called["position"] = (args, kwargs)
        return {"kind": "position", "args": args, "kwargs": kwargs}

    def fake_candle_analysis(*args):
        called["candle"] = args
        return {"kind": "candle", "args": args}

    container = DependencyContainer(
        app_config=_build_app_config(),
        notifier_factory=lambda: fake_notifier,
        oanda_factory=fake_oanda,
        position_control_factory=fake_position_control,
        candle_analysis_factory=fake_candle_analysis,
    )

    notifier = container.create_notifier()
    base_oa = container.create_base_oanda(use_sub_account=True)
    position_control = container.create_position_control(is_live=True, notifier=notifier)
    candle = container.create_candle_analysis(base_oa, 0)

    assert notifier is fake_notifier
    assert called["oanda"] == ("l2-id", "l-token", "live")
    assert called["position"][0] == (True,)
    assert called["position"][1]["account_config"].live_account_id == "l-id"
    assert called["position"][1]["notifier"] is fake_notifier
    assert called["candle"] == (base_oa, 0)
    assert position_control["kind"] == "position"
    assert candle["kind"] == "candle"
