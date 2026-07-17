import classPosition
from ogami_oanda.adapters.repositories.csv_trade_history import (
    CsvTradeHistoryRepository,
)
from tests.fakes import FakeNotifier


class FakeOanda:
    def __init__(self, account_id, access_token, environment):
        self.account_id = account_id
        self.access_token = access_token
        self.environment = environment
        self.stop_loss_updates = []

    def TradeCRCDO_exe(self, trade_id, payload):
        self.stop_loss_updates.append((trade_id, payload))
        return {"error": 0}


def test_order_information_accepts_an_injected_oanda_factory():
    position = classPosition.order_information("injected", is_live=True, oanda_factory=FakeOanda)

    assert isinstance(position.oa, FakeOanda)
    assert position.oa.account_id == "test-live-account-2"

    position.select_oa(1)

    assert isinstance(position.oa, FakeOanda)
    assert position.oa.account_id == "test-live-account"


def test_order_information_sends_through_an_injected_notifier():
    notifier = FakeNotifier()
    position = classPosition.order_information("injected", is_live=False, oanda_factory=FakeOanda, notifier=notifier)

    position.send_line("trade", "closed")

    assert notifier.messages == [("trade closed", "practice", "USD_JPY")]


def test_order_information_writes_history_through_an_injected_repository(tmp_path):
    repository = CsvTradeHistoryRepository(tmp_path / "history.csv")
    position = classPosition.order_information("history", is_live=False, oanda_factory=FakeOanda, history_repository=repository)

    path = position.write_history_result({"name": "injected", "res": 1})

    assert path == str(repository.path)
    assert repository.path.read_text(encoding="utf-8").splitlines() == ["name,res", "injected,1"]


def test_legacy_lc_change_amends_stop_loss_after_trigger_and_wait_time():
    position = classPosition.order_information("lc", is_live=False, oanda_factory=FakeOanda, notifier=FakeNotifier())
    position.t_state = "OPEN"
    position.t_id = "trade-1"
    position.t_execution_price = 150.0
    position.t_price_diff = 0.1
    position.t_time_past_sec = 60
    position.plan_json = {"direction": 1, "lc_price": 149.8, "target_price": 150.0}
    position.lc_change_dic_arr = [{"exe": True, "ensure": 0.05, "trigger": 0.1, "time_after": 60}]

    position.lc_change()

    assert position.oa.stop_loss_updates == [
        ("trade-1", {"instrument": "USD_JPY", "stopLoss": {"price": "150.05", "timeInForce": "GTC"}})
    ]
    assert position.lc_change_dic_arr[0]["done"] is True
    assert position.plan_json["lc_price"] == 150.05


def test_legacy_lc_change_does_not_amend_a_non_open_trade():
    position = classPosition.order_information("lc", is_live=False, oanda_factory=FakeOanda, notifier=FakeNotifier())
    position.t_state = "CLOSED"
    position.lc_change_dic_arr = [{"exe": True, "ensure": 0.05, "trigger": 0.1, "time_after": 0}]

    position.lc_change()

    assert position.oa.stop_loss_updates == []
