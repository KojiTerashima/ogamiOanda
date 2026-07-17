import datetime

import pandas as pd
import pytest

import send_notice


class _FakeOanda:
    def __init__(self, account_id, token, environment):
        self.account_id = account_id
        self.token = token
        self.environment = environment


class _FakeOrder:
    def __init__(self, name, direction, target_price, priority, current_price=150.0):
        self.current_price = current_price
        self.lc_change = []
        self.exe_order_plan = {
            "name": name,
            "direction": direction,
            "target_price": target_price,
            "priority": priority,
        }


class _FakePositionSlot:
    def __init__(self, name):
        self.name = name
        self.life = False
        self.oa_mode = 2
        self.t_id = 0
        self.linkage_class_slots = []
        self.linkage_order_classes = []
        self.for_line_send_order_info = "registered "

    def order_plan_registration(self, order):
        self.life = True
        self.name = order.exe_order_plan["name"]
        self.plan_json = order.exe_order_plan
        return {"order_id": 1, "order_name": self.name, "order_result": {}}


@pytest.mark.characterization
def test_position_initial_and_reset_state_contract(monkeypatch):
    import classPosition

    monkeypatch.setattr(classPosition.classOanda, "Oanda", _FakeOanda)
    position = classPosition.order_information("baseline", is_live=False)

    assert position.name == "baseline"
    assert position.oa.environment == "practice"
    assert position.life is False
    assert position.waiting_order is False
    assert position.o_state == ""
    assert position.t_state == ""

    position.life = True
    position.o_id = "123"
    position.reset()

    assert position.life is False
    assert position.o_id == 0
    assert position.plan_json == {}


@pytest.mark.characterization
def test_inspection_dataframe_boundary_contract(candle_frame):
    import classInspection

    start = candle_frame["time_jp_dt"].min()
    end = candle_frame["time_jp_dt"].max()
    assert classInspection.Inspection.df_covers_range(candle_frame, start, end)

    target_time = pd.Timestamp("2026-01-02 00:15:00")
    sliced = classInspection.Inspection.slice_past_df_r(candle_frame.iloc[::-1], target_time, row_count=3)

    assert list(sliced["time_jp_dt"]) == [
        pd.Timestamp("2026-01-02 00:15:00"),
        pd.Timestamp("2026-01-02 00:10:00"),
        pd.Timestamp("2026-01-02 00:05:00"),
    ]
    incomplete_frame = pd.DataFrame(
        {
            "time_jp_dt": [
                pd.Timestamp("2026-01-02 00:14:00"),
                pd.Timestamp("2026-01-02 00:12:00"),
            ]
        }
    )
    with pytest.raises(ValueError, match="incomplete candle"):
        classInspection.Inspection.validate_analysis_boundary(
            incomplete_frame,
            datetime.datetime(2026, 1, 2, 0, 15),
            datetime.timedelta(minutes=5),
            "M5",
        )


@pytest.mark.characterization
def test_notice_routing_and_duplicate_contract(monkeypatch):
    import tokens

    tokens.WEBHOOK_URL_usdyen = "https://example.invalid/usd-jpy"
    tokens.WEBHOOK_URL_eurousd = "https://example.invalid/eur-usd"
    tokens.WEBHOOK_URL_audusd = "https://example.invalid/aud-usd"
    tokens.WEBHOOK_URL_inspection = "https://example.invalid/inspection"
    calls = []

    def post(url, json):
        calls.append((url, json))

    monkeypatch.setattr(send_notice.requests, "post", post)
    monkeypatch.setattr(send_notice, "line_send_last_message", "")
    monkeypatch.setattr(send_notice, "line_send_last_message_count", 0)

    send_notice.line_send("EUR_USD", "order")
    send_notice.line_send("inspection", "backtest")
    send_notice.line_send("repeat")
    send_notice.line_send("repeat")
    send_notice.line_send("repeat")

    assert [url for url, _ in calls] == [
        "https://example.invalid/eur-usd",
        "https://example.invalid/inspection",
        "https://example.invalid/usd-jpy",
        "https://example.invalid/usd-jpy",
    ]
    assert all(payload["allowed_mentions"] == {"parse": ["everyone"]} for _, payload in calls)
    assert all(payload["content"].startswith("@everyone ") for _, payload in calls)


@pytest.mark.characterization
def test_position_history_csv_header_and_append_contract(monkeypatch, tmp_path):
    import classPosition

    classPosition.order_information.result_dic_arr = []
    monkeypatch.setattr(classPosition.tk, "history_folder_path", f"{tmp_path}/", raising=False)
    position = classPosition.order_information("history", is_live=False, oanda_factory=_FakeOanda)
    first = {"name": "first", "res": 1, "pair": "USD_JPY"}
    second = {"name": "second", "res": -1, "pair": "USD_JPY"}

    history_path = position.write_history_result(first)
    position.write_history_result(second)

    history = pd.read_csv(history_path)
    assert list(history.columns) == ["name", "res", "pair"]
    assert history.to_dict("records") == [first, second]


@pytest.mark.characterization
def test_position_control_filters_near_candidates_before_assigning_normal_slots(monkeypatch):
    import classPositionControl
    import fGeneric

    controller = object.__new__(classPositionControl.position_control)
    controller.pair = "USD_JPY"
    controller.p = fGeneric.currency_pair(controller.pair)
    controller.position_classes = [_FakePositionSlot(f"c{index}") for index in range(15)]
    controller.max_position_num = 15
    controller.high_i_from = 14
    controller.high_i_to = 15
    controller.mid_i_from = 6
    controller.mid_i_to = 14
    controller.normal_i_from = 0
    controller.normal_i_to = 6
    controller.find_similar_active_order = lambda *args, **kwargs: {"is_exist": False}
    controller.print_classes_and_count = lambda: None
    monkeypatch.setattr(classPositionControl.notice, "line_send", lambda *args: None)
    near_first = _FakeOrder("near-first", 1, 150.000, priority=1)
    near_second = _FakeOrder("near-second", 1, 150.020, priority=1)
    far = _FakeOrder("far", 1, 150.050, priority=1)

    result = controller.order_class_add([near_first, near_second, far])

    assert result.count("registered") == 2
    assert [slot.name for slot in controller.position_classes[:2]] == ["near-first", "far"]
    assert all(slot.life is False for slot in controller.position_classes[2:])


@pytest.mark.characterization
@pytest.mark.parametrize(
    ("priority", "expected_index"),
    [(1, 0), (10, 6), (100, 14)],
)
def test_position_control_assigns_first_slot_in_each_priority_tier(monkeypatch, priority, expected_index):
    import classPositionControl
    import fGeneric

    controller = object.__new__(classPositionControl.position_control)
    controller.pair = "USD_JPY"
    controller.p = fGeneric.currency_pair(controller.pair)
    controller.position_classes = [_FakePositionSlot(f"c{index}") for index in range(15)]
    controller.max_position_num = 15
    controller.high_i_from = 14
    controller.high_i_to = 15
    controller.mid_i_from = 6
    controller.mid_i_to = 14
    controller.normal_i_from = 0
    controller.normal_i_to = 6
    controller.find_similar_active_order = lambda *args, **kwargs: {"is_exist": False}
    controller.print_classes_and_count = lambda: None
    monkeypatch.setattr(classPositionControl.notice, "line_send", lambda *args: None)

    controller.order_class_add([_FakeOrder(f"priority-{priority}", 1, 150.0, priority=priority)])

    assert controller.position_classes[expected_index].name == f"priority-{priority}"
