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


class _FrozenDateTime(datetime.datetime):
    current = datetime.datetime(2026, 1, 2, 10, 0, 0)

    @classmethod
    def now(cls, tz=None):
        if tz is None:
            return cls.current
        return tz.fromutc(cls.current.replace(tzinfo=tz))


class _QueuePriceOanda:
    def __init__(self, account_id, token, environment):
        self.account_id = account_id
        self.token = token
        self.environment = environment
        self.now_prices = []
        self.create_calls = []
        self.trade_crcdo_calls = []

    def NowPrice_exe(self, pair):
        if self.now_prices:
            price = self.now_prices.pop(0)
        else:
            price = {"ask": 150.0, "bid": 150.0}
        return {"error": 0, "data": price}

    def OrderCreate_dic_exe(self, payload):
        self.create_calls.append(payload)
        order = payload["order"]
        return {
            "data": {
                "cancel": False,
                "order_id": 99,
                "order_time": "2026/01/02 10:00:00",
                "execution_price": order.get("price", "0"),
                "json": {
                    "orderCreateTransaction": {
                        "units": order.get("units", "0"),
                        "takeProfitOnFill": order.get("takeProfitOnFill", {}),
                        "stopLossOnFill": order.get("stopLossOnFill", {}),
                    }
                },
            }
        }

    def TradeCRCDO_exe(self, trade_id, data):
        self.trade_crcdo_calls.append({"trade_id": trade_id, "data": data})
        return {"error": 0}


class _FakeCandleMeta:
    def cal_move_ave(self, times):
        return 0.12


class _FakeWatchingCandleAnalysis:
    def __init__(self, current_price=150.0):
        self.current_price = current_price
        self.candle_meta_class = _FakeCandleMeta()
        self.candle_meta_class_hour = _FakeCandleMeta()
        self.peaks_class = type(
            "Peaks",
            (),
            {"peaks_original": [{"latest_body_peak_price": current_price}]},
        )()


class _FakeCandleAnalysisForLc:
    def __init__(self, direction, df_r):
        peaks = type(
            "Peaks",
            (),
            {"peaks_original": [{"count": 3, "direction": direction}], "df_r_original": df_r},
        )()
        self.peaks_class = peaks
        self.peaks_class_hour = peaks


def _new_position(monkeypatch, name="watch-test"):
    import classPosition

    _FrozenDateTime.current = datetime.datetime(2026, 1, 2, 10, 0, 0)
    monkeypatch.setattr(classPosition.datetime, "datetime", _FrozenDateTime)
    monkeypatch.setattr(classPosition.notice, "line_send", lambda *args: None)
    position = classPosition.order_information(name, is_live=False, oanda_factory=_QueuePriceOanda)
    position.send_line_exe = False
    return position


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


@pytest.mark.characterization
def test_position_control_skips_new_order_when_near_active_order_exists_even_with_different_source(monkeypatch):
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
    controller.print_classes_and_count = lambda: None
    monkeypatch.setattr(classPositionControl.notice, "line_send", lambda *args: None)

    active_slot = controller.position_classes[0]
    active_slot.life = True
    active_slot.name = "existing-active"
    active_slot.plan_json = {
        "direction": 1,
        "target_price": 150.0,
        "source": "counter",
        "line_strategy": "counter",
    }
    active_slot.o_state = "PENDING"
    active_slot.t_state = ""

    new_order = _FakeOrder("new-line-order", 1, 150.02, priority=1)
    new_order.exe_order_plan["source"] = "line"
    new_order.exe_order_plan["line_strategy"] = "future_break"

    result = controller.order_class_add([new_order])

    assert result == 0
    assert [slot.name for slot in controller.position_classes if slot.life] == ["existing-active"]


@pytest.mark.characterization
def test_position_control_returns_zero_when_priority_tier_is_full(monkeypatch):
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

    for slot in controller.position_classes[controller.normal_i_from:controller.normal_i_to]:
        slot.life = True
        slot.name = f"filled-{slot.name}"

    result = controller.order_class_add([_FakeOrder("blocked", 1, 150.0, priority=1)])

    assert result == 0
    assert all(slot.life is True for slot in controller.position_classes[:6])
    assert all(slot.name.startswith("filled-") for slot in controller.position_classes[:6])


@pytest.mark.characterization
def test_position_control_returns_zero_when_batch_would_overflow_tier(monkeypatch):
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

    for slot in controller.position_classes[controller.normal_i_from:controller.normal_i_to - 1]:
        slot.life = True

    result = controller.order_class_add(
        [
            _FakeOrder("overflow-1", 1, 150.0, priority=1),
            _FakeOrder("overflow-2", 1, 150.05, priority=1),
        ]
    )

    assert result == 0
    assert controller.position_classes[5].life is False


@pytest.mark.characterization
def test_stop_watching_requires_30_second_hold_before_make_order(monkeypatch):
    position = _new_position(monkeypatch, "stop-watch")
    position.life = True
    position.waiting_order = True
    position.o_state = "Watching"
    position.plan_json = {"direction": 1, "target_price": 150.0, "type": "STOP"}
    position.order_register_time = _FrozenDateTime.current
    position.oa.now_prices = [{"ask": 150.01, "bid": 150.0}, {"ask": 150.02, "bid": 150.0}]
    calls = []
    monkeypatch.setattr(position, "watching_for_position_make_order", lambda: calls.append("make-order"))

    position.watching_for_position(None)

    assert calls == []
    assert position.step1_filled is True

    _FrozenDateTime.current = _FrozenDateTime.current + datetime.timedelta(seconds=31)
    position.watching_for_position(None)

    assert calls == ["make-order"]
    assert position.step1_filled is False
    assert position.step1_keeping_second >= 30


@pytest.mark.characterization
def test_stop_watching_timeout_closes_waiting_order_without_cross(monkeypatch):
    position = _new_position(monkeypatch, "stop-timeout")
    position.life = True
    position.waiting_order = True
    position.o_state = "Watching"
    position.plan_json = {"direction": 1, "target_price": 150.0, "type": "STOP"}
    position.order_timeout_min = 1
    position.order_register_time = _FrozenDateTime.current - datetime.timedelta(seconds=61)
    position.oa.now_prices = [{"ask": 149.98, "bid": 149.97}]

    position.watching_for_position(None)

    assert position.life is False
    assert position.step1_filled is False


@pytest.mark.characterization
def test_limit_watching_requires_reverse_then_recover_before_make_order(monkeypatch):
    position = _new_position(monkeypatch, "limit-watch")
    position.life = True
    position.waiting_order = True
    position.o_state = "Watching"
    position.plan_json = {"direction": 1, "target_price": 150.0, "type": "LIMIT"}
    position.order_register_time = _FrozenDateTime.current
    position.oa.now_prices = [
        {"ask": 149.95, "bid": 149.94},
        {"ask": 150.05, "bid": 150.04},
        {"ask": 150.06, "bid": 150.05},
    ]
    calls = []
    monkeypatch.setattr(position, "watching_for_position_make_order", lambda: calls.append("make-order"))

    position.watching_for_position(None)
    assert calls == []
    assert position.step1_filled is True
    assert position.step2_filled is False

    _FrozenDateTime.current = _FrozenDateTime.current + datetime.timedelta(seconds=11)
    position.watching_for_position(None)
    assert calls == []
    assert position.step2_filled is True

    _FrozenDateTime.current = _FrozenDateTime.current + datetime.timedelta(seconds=21)
    position.watching_for_position(None)

    assert calls == ["make-order"]
    assert position.step1_filled is False
    assert position.step2_filled is False
    assert position.step2_keeping_second >= 20


@pytest.mark.characterization
def test_lc_change_executes_at_trigger_boundary_and_updates_plan(monkeypatch):
    position = _new_position(monkeypatch, "lc-change")
    position.t_state = "OPEN"
    position.t_time_past_sec = 120
    position.t_price_diff = 0.03
    position.t_pl_pips = 3
    position.t_execution_price = 150.0
    position.t_id = 77
    position.plan_json = {"direction": 1, "lc_price": 149.9, "target_price": 150.0, "lc_range": 0.1}
    position.lc_change_dic_arr = [{"exe": True, "trigger": 0.03, "ensure": 0.01, "time_after": 0}]

    position.lc_change()

    assert position.lc_change_num == 1
    assert position.plan_json["lc_price"] == 150.01
    assert position.lc_change_dic_arr[0]["done"] is True
    assert position.oa.trade_crcdo_calls == [
        {
            "trade_id": 77,
            "data": {"instrument": "USD_JPY", "stopLoss": {"price": "150.01", "timeInForce": "GTC"}},
        }
    ]


@pytest.mark.characterization
def test_candle_lc_change_uses_previous_candle_after_30_second_open_boundary(monkeypatch):
    position = _new_position(monkeypatch, "lc-candle")
    _FrozenDateTime.current = datetime.datetime(2026, 1, 2, 10, 5, 10)
    position.t_state = "OPEN"
    position.t_time_past_sec = 30
    position.t_pl_pips = 8
    position.t_execution_price = 150.0
    position.t_id = 88
    position.t_json = {"price": 150.0}
    position.plan_json = {"direction": 1, "lc_price": 149.9, "target_price": 150.2}
    frame = pd.DataFrame(
        [
            {"time_jp": "2026/01/02 10:05:00", "open": 150.12, "close": 150.14, "high": 150.16, "low": 150.11},
            {"time_jp": "2026/01/02 10:00:00", "open": 150.11, "close": 150.13, "high": 150.15, "low": 150.12},
        ]
    )
    candle_analysis = _FakeCandleAnalysisForLc(direction=1, df_r=frame)

    position.lc_change_from_candle(candle_analysis)

    assert position.lc_change_num == 1
    assert position.plan_json["lc_price"] == 150.105
    assert position.lc_change_from_candle_lc_price == pytest.approx(150.105)
    assert position.oa.trade_crcdo_calls == [
        {
            "trade_id": 88,
            "data": {"instrument": "USD_JPY", "stopLoss": {"price": "150.105", "timeInForce": "GTC"}},
        }
    ]


@pytest.mark.characterization
def test_after_close_trade_function_updates_totals_history_and_csv(monkeypatch, tmp_path):
    import classPosition

    position = _new_position(monkeypatch, "close-test-12345")
    monkeypatch.setattr(position, "send_line", lambda *args: None)
    monkeypatch.setattr(classPosition.tk, "history_folder_path", f"{tmp_path}/", raising=False)

    classPosition.order_information.total_yen = 0
    classPosition.order_information.total_yen_max = 0
    classPosition.order_information.total_yen_min = float("inf")
    classPosition.order_information.total_price_diff = 0
    classPosition.order_information.total_price_diff_max = 0
    classPosition.order_information.total_price_diff_min = float("inf")
    classPosition.order_information.total_pips = 0
    classPosition.order_information.total_pips_max = 0
    classPosition.order_information.total_pips_min = float("inf")
    classPosition.order_information.plus_yen_position_num = 0
    classPosition.order_information.minus_yen_position_num = 0
    classPosition.order_information.lc_change_num = 0
    classPosition.order_information.result_dic_arr = []
    classPosition.order_information.history_plus_minus = [0]
    classPosition.order_information.history_names = ["0"]
    classPosition.order_information.history_name_plus_minus = []
    classPosition.order_information.before_latest_price_diff = 0
    classPosition.order_information.before_latest_pl_pips = 0
    classPosition.order_information.before_latest_plu = 0
    classPosition.order_information.before_latest_name = ""

    position.life = True
    position.pair = "USD_JPY"
    position.o_id = 41
    position.t_id = 51
    position.o_time = "2026/01/02 09:00:00"
    position.t_time = "2026/01/02 09:10:00"
    position.name_ymdhms = "20260102100000"
    position.plan_json = {
        "direction": 1,
        "target_price": 150.05,
        "lc_price": 149.95,
        "lc_price_original": 149.9,
        "lc_range": 0.1,
        "tp_price": 150.25,
        "tp_price_original": 150.3,
        "tp_range": 0.2,
        "memo": "close memo",
    }
    position.for_line_send_order_info_at_close = "close summary"
    position.positions_information = {"open_positions": [], "pending_positions": []}
    position.order_class = type("Order", (), {"memo": "order memo"})()
    position.move_ave5 = 0.05
    position.move_ave60 = 0.15
    position.current_candle_price_gap = 0.02
    position.gap_target_price_pips = 3.5
    position.win_max_pips = 12
    position.lose_max_pips = -4
    position.win_max_price = 150.22
    position.lose_max_price = 149.96
    position.win_max_price_diff_yen = 1200
    position.lose_max_price_diff_yen = -400
    position.lc_change_str = "(3p-1p)"
    position.t_json = {
        "state": "CLOSED",
        "realizedPL": "200",
        "price": "150.0",
        "averageClosePrice": "150.2",
        "initialUnits": "1000",
        "currentUnits": "0",
        "time_past": 600,
    }

    position.after_close_trade_function()

    result = classPosition.order_information.result_dic_arr[-1]
    history = pd.read_csv(tmp_path / "history.csv")

    assert position.life is False
    assert classPosition.order_information.total_yen == 200.0
    assert classPosition.order_information.total_price_diff == 0.2
    assert classPosition.order_information.total_pips == 20.0
    assert classPosition.order_information.plus_yen_position_num == 1
    assert classPosition.order_information.minus_yen_position_num == 0
    assert classPosition.order_information.before_latest_price_diff == 0.2
    assert classPosition.order_information.before_latest_pl_pips == 20.0
    assert classPosition.order_information.before_latest_name == "close-test-12345"
    assert classPosition.order_information.history_plus_minus[-1] == 20.0
    assert classPosition.order_information.history_names[-1] == "close-test-12345"
    assert classPosition.order_information.history_name_plus_minus[-1] == {
        "name": "close-test-",
        "price_diff": 0.2,
        "pl_pips": 20.0,
    }
    assert result["name"] == "close-test-12345"
    assert result["name_only"] == "close-test-"
    assert result["res"] == "200"
    assert result["pl_per_units"] == 20.0
    assert result["units"] == "1000.0"
    assert result["lc_range"] == 10.0
    assert result["tp_range"] == 20.0
    assert result["move_ave5"] == 5.0
    assert result["move_ave60"] == 15.0
    assert result["current_price_gap"] == 2.0
    assert result["rr"] == 2.0
    assert result["target_price_range"] == 3.5
    assert history.iloc[-1]["name"] == "close-test-12345"
    assert history.iloc[-1]["res"] == 200
    assert history.iloc[-1]["tradeID"] == 51


@pytest.mark.characterization
def test_trade_timeout_threshold_does_not_close_open_trade(monkeypatch):
    position = _new_position(monkeypatch, "trade-timeout")
    position.life = True
    position.trade_timeout_min = 1
    position.lose_hold_time_sec = 120
    position.current_price = 149.95
    position.t_json = {
        "id": 61,
        "state": "OPEN",
        "initialUnits": "1000",
        "currentUnits": "1000",
        "openTime": "2026/01/02 09:00:00",
        "time_past": 61,
        "price": 150.0,
        "unrealizedPL": "-50",
    }
    close_calls = []
    monkeypatch.setattr(position, "close_trade", lambda units=None: close_calls.append(units))

    position.trade_update_and_close()

    assert close_calls == []
    assert position.life is True
    assert position.t_state == "OPEN"
    assert position.t_time_past_sec == 61
    assert position.t_price_diff == -0.05


@pytest.mark.characterization
def test_linkage_pending_order_is_closed_when_main_order_completes(monkeypatch):
    main_position = _new_position(monkeypatch, "main-link")
    linked_position = _new_position(monkeypatch, "linked-pending")
    linked_position.name = "linked-pending"
    linked_position.o_state = "PENDING"
    linked_position.life = True
    main_position.linkage_class_slots = [linked_position]
    close_calls = []
    monkeypatch.setattr(linked_position, "close_order", lambda: close_calls.append(linked_position.name))

    main_position.linkage_change_order_from_detect_change()

    assert close_calls == ["linked-pending"]


@pytest.mark.characterization
def test_linkage_loss_moves_opposite_open_position_lc(monkeypatch):
    main_position = _new_position(monkeypatch, "main-loss")
    linked_position = _new_position(monkeypatch, "linked-open")
    main_position.plan_json = {"direction": 1}
    main_position.t_price_diff = -0.03
    linked_position.life = True
    linked_position.t_state = "OPEN"
    linked_position.t_id = 75
    linked_position.plan_json = {
        "direction": -1,
        "target_price": 150.0,
        "lc_range": 0.05,
        "lc_price": 150.2,
    }
    main_position.linkage_class_slots = [linked_position]

    main_position.linkage_change_trade_from_detect_change()

    assert main_position.linkage_done is True
    assert linked_position.linkage_done is True
    assert linked_position.plan_json["lc_price"] == 150.05
    assert linked_position.oa.trade_crcdo_calls == [
        {
            "trade_id": 75,
            "data": {"instrument": "USD_JPY", "stopLoss": {"price": "150.05", "timeInForce": "GTC"}},
        }
    ]


@pytest.mark.characterization
def test_close_hedge_positions_keeps_profitable_opposites_open(monkeypatch):
    import classPositionControl

    class _HedgePosition:
        def __init__(self, name, direction, unrealized_pl):
            self.name = name
            self.life = True
            self.t_unrealize_pl = unrealized_pl
            self.plan_json = {
                "target_price": 150.0,
                "direction": direction,
                "units": 1000,
            }
            self.close_calls = 0

        def close_trade(self):
            self.close_calls += 1

    controller = object.__new__(classPositionControl.position_control)
    long_position = _HedgePosition("long", 1, 0.3)
    short_position = _HedgePosition("short", -1, 0.3)
    controller.position_classes = [long_position, short_position]
    monkeypatch.setattr(classPositionControl.notice, "line_send", lambda *args: None)
    monkeypatch.setattr(classPositionControl.tk, "setting_json", {"hedge_close_on": False}, raising=False)

    controller.close_hedge_positions()

    assert long_position.close_calls == 0
    assert short_position.close_calls == 0


@pytest.mark.characterization
def test_catch_up_position_restores_matching_trades_into_first_empty_slots(monkeypatch):
    import classPositionControl

    class _CatchUpOanda:
        def OpenTrades_exe(self):
            trades = [
                {
                    "id": 701,
                    "instrument": "USD_JPY",
                    "price": "150.01",
                    "currentUnits": "1000",
                    "takeProfitOrder": {"price": "150.21"},
                    "stopLossOrder": {"price": "149.91"},
                },
                {
                    "id": 999,
                    "instrument": "EUR_USD",
                    "price": "1.1050",
                    "currentUnits": "1000",
                },
                {
                    "id": 702,
                    "instrument": "USD_JPY",
                    "price": "149.80",
                    "currentUnits": "-500",
                    "takeProfitOrder": {"price": "149.60"},
                    "stopLossOrder": {"price": "149.95"},
                },
            ]
            return {"data": trades, "json": {"trades": trades}}

    controller = object.__new__(classPositionControl.position_control)
    controller.pair = "USD_JPY"
    controller.oa2 = _CatchUpOanda()
    occupied = _new_position(monkeypatch, "occupied")
    occupied.life = True
    slot1 = _new_position(monkeypatch, "slot1")
    slot2 = _new_position(monkeypatch, "slot2")
    controller.position_classes = [occupied, slot1, slot2]
    controller.print_classes_and_count = lambda: None

    controller.catch_up_position_and_del_order()

    assert occupied.name == "occupied"
    assert slot1.life is True
    assert slot1.name.startswith("既存0_")
    assert slot1.o_id == -1
    assert slot1.t_id == 701
    assert slot1.o_json["state"] == "FILLED"
    assert slot1.plan_json["target_price"] == 150.01
    assert slot1.plan_json["direction"] == 1
    assert slot2.life is True
    assert slot2.name.startswith("既存1_")
    assert slot2.t_id == 702
    assert slot2.plan_json["target_price"] == 149.8
    assert slot2.plan_json["direction"] == -1


@pytest.mark.characterization
def test_position_check_and_life_check_return_watch_pending_open_summary():
    import classPositionControl

    class _SummarySlot:
        def __init__(
            self,
            *,
            name,
            life,
            o_state,
            t_state,
            priority,
            target_price,
            direction,
            units,
            order_time,
            order_age,
            unrealized_pl,
            t_time_past_sec,
            lc_change_status,
            source=None,
            line_strategy=None,
            step1_filled=False,
            step1_keeping_second=0,
            order_register_time=None,
        ):
            self.name = name
            self.life = life
            self.o_state = o_state
            self.t_state = t_state
            self.priority = priority
            self.plan_json = {
                "target_price": target_price,
                "direction": direction,
                "source": source,
                "line_strategy": line_strategy,
            }
            self.o_json = {"units": units}
            self.o_time = order_time
            self.o_time_past_sec = order_age
            self.t_json = {"unrealizedPL": unrealized_pl}
            self.t_unrealize_pl = float(unrealized_pl)
            self.t_time_past_sec = t_time_past_sec
            self.t_pl_pips = 12
            self.lc_change_status = lc_change_status
            self.step1_filled = step1_filled
            self.step1_keeping_second = step1_keeping_second
            self.order_register_time = order_register_time or _FrozenDateTime.current
            self.try_update_num = 0
            self.try_update_limit = 2

        def count_up_position_check(self):
            self.try_update_num += 1

        def life_set(self, value):
            self.life = value

    controller = object.__new__(classPositionControl.position_control)
    controller.position_classes = [
        _SummarySlot(
            name="watching",
            life=True,
            o_state="Watching",
            t_state="",
            priority=1,
            target_price=150.1,
            direction=1,
            units="1000",
            order_time="2026/01/02 10:00:00",
            order_age=15,
            unrealized_pl="0",
            t_time_past_sec=0,
            lc_change_status="",
            step1_filled=True,
            step1_keeping_second=12.6,
            order_register_time=datetime.datetime(2026, 1, 2, 10, 0, 0),
        ),
        _SummarySlot(
            name="pending",
            life=True,
            o_state="PENDING",
            t_state="",
            priority=5,
            target_price=150.2,
            direction=-1,
            units="1000",
            order_time="2026/01/02 09:55:00",
            order_age=120,
            unrealized_pl="0",
            t_time_past_sec=0,
            lc_change_status="",
            source="line",
            line_strategy="future_break",
        ),
        _SummarySlot(
            name="open",
            life=True,
            o_state="FILLED",
            t_state="OPEN",
            priority=10,
            target_price=149.9,
            direction=1,
            units="2000",
            order_time="2026/01/02 09:30:00",
            order_age=180,
            unrealized_pl="120",
            t_time_past_sec=240,
            lc_change_status="LC-updated",
            source="line",
            line_strategy="counter",
        ),
        _SummarySlot(
            name="closed",
            life=False,
            o_state="CANCELLED",
            t_state="CLOSED",
            priority=0,
            target_price=0,
            direction=1,
            units="0",
            order_time="2026/01/02 09:00:00",
            order_age=0,
            unrealized_pl="0",
            t_time_past_sec=0,
            lc_change_status="",
        ),
    ]

    life_result = controller.life_check()
    position_result = controller.position_check()

    assert life_result["life_exist"] is True
    assert "LC-updated" in life_result["one_line_comment"]
    assert position_result["position_exist"] is True
    assert position_result["order_exist"] is True
    assert position_result["max_priority_position"] == 10
    assert position_result["max_priority_order"] == 5
    assert position_result["max_position_time_sec"] == 240
    assert position_result["max_order_time_sec"] == 120
    assert position_result["total_pl"] == 120.0
    assert position_result["open_positions"][0]["name"] == "open"
    assert position_result["open_positions"][0]["source"] == "line"
    assert position_result["open_positions"][0]["line_strategy"] == "counter"
    assert position_result["pending_positions"][0]["name"] == "pending"
    assert position_result["pending_positions"][0]["direction"] == -1
    assert position_result["watching_list"] == [
        {
            "name": "watching",
            "target": 150.1,
            "direction": 1,
            "order_time": "20260102100000",
            "state": True,
            "keeping": 13.0,
        }
    ]
    assert "09:55" in position_result["name_list"]
    assert "09:30" in position_result["name_list"]


@pytest.mark.characterization
def test_find_similar_active_order_filters_by_source_and_line_strategy():
    import classPositionControl
    import fGeneric

    class _ActiveSlot:
        def __init__(self, name, direction, target_price, source, line_strategy):
            self.name = name
            self.life = True
            self.plan_json = {
                "direction": direction,
                "target_price": target_price,
                "source": source,
                "line_strategy": line_strategy,
            }
            self.o_state = "PENDING"
            self.t_state = ""

    controller = object.__new__(classPositionControl.position_control)
    controller.pair = "USD_JPY"
    controller.p = fGeneric.currency_pair(controller.pair)
    controller.position_classes = [
        _ActiveSlot("different-source", 1, 150.01, "counter", "future_break"),
        _ActiveSlot("different-strategy", 1, 150.015, "line", "counter"),
        _ActiveSlot("matching", 1, 150.02, "line", "future_break"),
        _ActiveSlot("far", 1, 150.08, "line", "future_break"),
    ]

    result = controller.find_similar_active_order(
        direction=1,
        target_price=150.0,
        threshold_pips=3,
        source="line",
        line_strategy="future_break",
    )

    assert result == {
        "is_exist": True,
        "name": "matching",
        "target_price": 150.02,
        "direction": 1,
        "gap_pips": 2.0,
        "o_state": "PENDING",
        "t_state": "",
        "source": "line",
        "line_strategy": "future_break",
    }


@pytest.mark.characterization
def test_pending_order_timeout_closes_order_and_records_forced_cancel(monkeypatch):
    position = _new_position(monkeypatch, "pending-timeout")
    position.life = True
    position.o_id = 88
    position.o_time = "2026/01/02 09:00:00"
    position.order_timeout_min = 1
    position.o_json = {"state": "PENDING", "time_past": 61}
    position.for_api_json = {"order": {"units": "1000"}}
    position.name_ymdhms = "20260102100000"
    position.move_ave5 = 0.05
    position.move_ave60 = 0.1
    position.current_candle_price_gap = 0.02
    position.gap_target_price_pips = 2.5
    position.plan_json = {
        "target_price": 150.0,
        "lc_price": 149.9,
        "lc_price_original": 149.85,
        "lc_range": 0.1,
        "tp_price": 150.2,
        "tp_price_original": 150.25,
        "tp_range": 0.2,
    }
    close_calls = []
    history_rows = []
    monkeypatch.setattr(position, "close_order", lambda: close_calls.append("closed") or "closed")
    monkeypatch.setattr(position, "write_history_result", lambda result: history_rows.append(result))

    position.order_update_and_close()

    assert close_calls == ["closed"]
    assert position.o_state == "PENDING"
    assert position.o_time_past_sec == 61
    assert history_rows[0]["name"] == "pending-timeout"
    assert history_rows[0]["memo"] == "Order強制キャンセル"
    assert history_rows[0]["units"] == "1000"
    assert history_rows[0]["target_price_range"] == 2.5
