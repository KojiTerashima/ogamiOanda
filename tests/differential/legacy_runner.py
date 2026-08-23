from __future__ import annotations

import contextlib
import importlib
import io
import json
import os
import socket
import sys
import types
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from .scenario import DifferentialScenario


@dataclass(frozen=True)
class LegacyRunnerResult:
    trace: dict[str, Any]
    log: str


class LegacyRunnerError(RuntimeError):
    pass


def run_legacy_scenario(scenario: DifferentialScenario) -> LegacyRunnerResult:
    with _legacy_sandbox(scenario) as sandbox:
        output = io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            if scenario.kind == "analysis_order":
                trace = _run_analysis_order(scenario)
            elif scenario.kind == "order_payload":
                trace = _run_order_payload(scenario)
            elif scenario.kind == "position_lifecycle":
                trace = _run_position_lifecycle(scenario)
            elif scenario.kind == "live_schedule":
                trace = _run_live_schedule(scenario)
            else:
                raise LegacyRunnerError(f"Unsupported scenario kind: {scenario.kind}")
        sandbox.assert_no_network_calls()
        return LegacyRunnerResult(trace=trace, log=output.getvalue())


def _run_analysis_order(scenario: DifferentialScenario) -> dict[str, Any]:
    classCandleAnalysis = importlib.import_module("classCandleAnalysis")
    fLineAnalysis = importlib.import_module("fLineAnalysis")
    fAnalysis_order_Main = importlib.import_module("fAnalysis_order_Main")
    _assert_module_paths(
        {
            "classCandleAnalysis": classCandleAnalysis,
            "fLineAnalysis": fLineAnalysis,
            "fAnalysis_order_Main": fAnalysis_order_Main,
        }
    )

    frames = _legacy_frame_store(scenario.pair)
    current_price = float(scenario.payload["current_price"])

    candle = classCandleAnalysis.candleAnalysis(
        None,
        scenario.pair,
        0,
        m5_df_r=frames["M5"].copy(),
        h1_df_r=frames["H1"].copy(),
        m30_df_r=frames["M30"].copy(),
        s5_df_r=frames["S5"].copy(),
        current_price=current_price,
    )

    analysis_cls = getattr(fLineAnalysis, "_LegacyMainAnalysis", None)
    if analysis_cls is None:
        analysis_cls = getattr(fLineAnalysis, "MainAnalysis", None)
    if analysis_cls is None:
        raise LegacyRunnerError("fLineAnalysis analysis class not found")

    analysis = analysis_cls(candle, None, "inspection")
    profile = analysis.each_pair_line_strategy_profile
    line_class_m5_l = fLineAnalysis.LineStrengthCal(candle, "m5", 60)
    line_class_m5_s = fLineAnalysis.LineStrengthCal(candle, "m5", 30)
    rsi_info = {
        "rsi_1": analysis.df_r_m5.iloc[0].get("RSI"),
        "rsi_2": analysis.df_r_m5.iloc[1].get("RSI"),
        "rsi_3": analysis.df_r_m5.iloc[2].get("RSI"),
    }
    line_context = profile.calculate_line_strength(
        analysis,
        line_class_m5_l,
        line_class_m5_s,
        analysis.line_class_h1_l,
        analysis.line_class_h1_s,
        analysis.current_price,
        analysis.df_r_m5.iloc[0]["time_jp"],
        rsi_info,
    )
    grouped = profile.group_lines(line_context)

    coordinator = grouped["coordinator"]
    selected_immediate = coordinator.select_line_candidates(
        grouped["immediate_candidates"],
        grouped["rsi_info"],
        grouped["decision_time"],
        "immediate",
        profile.immediate_recommended_reasons,
    )
    selected_future_resist = coordinator.select_line_candidates(
        grouped["future_resist_candidates"],
        grouped["rsi_info"],
        grouped["decision_time"],
        "future_resist",
        profile.future_resist_recommended_reasons,
    )
    selected_future_break = coordinator.select_line_candidates(
        grouped["future_break_candidates"],
        grouped["rsi_info"],
        grouped["decision_time"],
        "future_break",
        profile.future_break_recommended_reasons,
    )

    wrapped = fAnalysis_order_Main.wrap_all_analysis(candle, None, "inspection")

    return {
        "pair": scenario.pair,
        "kind": scenario.kind,
        "scenario_id": scenario.scenario_id,
        "events": [
            {
                "kind": "analysis",
                "decision_time": analysis.df_r_m5.iloc[0]["time_jp"],
                "current_price": current_price,
                "raw_candidate_counts": {
                    "immediate": len(grouped["immediate_candidates"]),
                    "future_resist": len(grouped["future_resist_candidates"]),
                    "future_break": len(grouped["future_break_candidates"]),
                },
                "selected_candidate_counts": {
                    "immediate": len(selected_immediate),
                    "future_resist": len(selected_future_resist),
                    "future_break": len(selected_future_break),
                },
                "legacy_plans": [_legacy_plan_summary(dict(order.exe_order_plan)) for order in wrapped.exe_order_classes],
            }
        ],
    }


def _run_order_payload(scenario: DifferentialScenario) -> dict[str, Any]:
    classOrderCreate = importlib.import_module("classOrderCreate")
    _assert_module_paths({"classOrderCreate": classOrderCreate})
    order_input = dict(scenario.payload["order_input"])
    order_input.setdefault("pair", scenario.pair)
    if "candle_analysis_class" not in order_input:
        order_input["candle_analysis_class"] = _LegacyCandleAnalysisStub()
    order = classOrderCreate.Order(order_input)

    return {
        "pair": scenario.pair,
        "kind": scenario.kind,
        "scenario_id": scenario.scenario_id,
        "events": [
            {
                "kind": "order_payload",
                "plan": _legacy_plan_summary(dict(order.exe_order_plan)),
                "payload": dict(order.data.get("order", {})),
            }
        ],
    }


def _run_position_lifecycle(scenario: DifferentialScenario) -> dict[str, Any]:
    classPositionControl = importlib.import_module("classPositionControl")
    _assert_module_paths({"classPositionControl": classPositionControl})

    controller = classPositionControl.position_control(False, scenario.pair)
    registration_result = None

    order_specs = scenario.payload["position"].get("orders", [])
    if order_specs:
        classOrderCreate = importlib.import_module("classOrderCreate")
        _assert_module_paths({"classOrderCreate": classOrderCreate})
        orders = [classOrderCreate.Order(dict(spec)) for spec in order_specs]
        registration_result = controller.order_class_add(orders)

    summary = controller.position_check()
    life = controller.life_check()

    return {
        "pair": scenario.pair,
        "kind": scenario.kind,
        "scenario_id": scenario.scenario_id,
        "events": [
            {
                "kind": "position_lifecycle",
                "registration": {
                    "accepted_count": 0,
                    "rejected_count": 0,
                    "raw_result": registration_result,
                },
                "counts": {
                    "watching": len(summary.get("watching_list", [])),
                    "pending": len(summary.get("pending_positions", [])),
                    "open": len(summary.get("open_positions", [])),
                    "life_exist": bool(life.get("life_exist", False)),
                },
            },
        ],
    }


def _run_live_schedule(scenario: DifferentialScenario) -> dict[str, Any]:
    main_exe = importlib.import_module("main_exe")
    import fGeneric

    _assert_module_paths({"main_exe": main_exe, "fGeneric": fGeneric})

    fGeneric.set_current_pair(scenario.pair)
    app = main_exe.main()
    now = datetime.fromisoformat(str(scenario.payload["live"]["now"]))
    app.now = now
    app.time_hour = now.hour
    app.time_min = now.minute
    app.time_sec = now.second

    if scenario.payload["live"].get("first_exe") is not None:
        app.first_exe = bool(scenario.payload["live"]["first_exe"])
    if scenario.payload["live"].get("latest_exe_time"):
        app.latest_exe_time = datetime.fromisoformat(str(scenario.payload["live"]["latest_exe_time"]))

    before_first_exe = bool(app.first_exe)
    result = app.exe_manage()
    if now.weekday() == 6:
        decision = "market_closed"
    elif before_first_exe and app.first_exe is False:
        decision = "analyze"
    elif result == 0:
        decision = "update_only"
    else:
        decision = "idle"

    return {
        "pair": scenario.pair,
        "kind": scenario.kind,
        "scenario_id": scenario.scenario_id,
        "events": [
            {
                "kind": "live_schedule",
                "decision": decision,
                "accepted_count": 0,
                "rejected_count": 0,
                "plan_count": 0,
            }
        ],
    }


class _LegacyFakeOanda:
    def __init__(self, accountID, access_token, env):
        self.account_id = accountID
        self.access_token = access_token
        self.environment = env
        self.now_price_queue: list[dict[str, float]] = []
        self.orders: dict[str, dict[str, Any]] = {}
        self.trades: dict[str, dict[str, Any]] = {}
        self.created_payloads: list[dict[str, Any]] = []
        self.crcdo_calls: list[dict[str, Any]] = []

    def NowPrice_exe(self, instrument):
        if self.now_price_queue:
            payload = self.now_price_queue.pop(0)
        else:
            mid = 150.0 if instrument.endswith("JPY") else 1.1
            payload = {"bid": mid, "ask": mid, "mid": mid, "spread": 0.0}
        return {"error": 0, "data": payload}

    def InstrumentsCandles_multi_exe(self, pair, params, roop):
        granularity = str(params.get("granularity", "M5"))
        frame = _legacy_frame_store(pair).get(granularity)
        if frame is None:
            frame = _legacy_frame_store(pair)["M5"]
        return {"error": 0, "data": frame}

    def OrderCreate_dic_exe(self, payload):
        self.created_payloads.append(payload)
        order_id = str(1000 + len(self.created_payloads))
        order = {
            "id": order_id,
            "state": "PENDING",
            "tradeOpenedID": None,
            "price": payload["order"].get("price", "0"),
            "units": payload["order"].get("units", "0"),
            "instrument": payload["order"].get("instrument", "USD_JPY"),
        }
        self.orders[order_id] = order
        return {
            "data": {
                "cancel": False,
                "order_id": order_id,
                "order_time": "2026/01/02 12:00:00",
                "execution_price": order["price"],
                "json": {
                    "orderCreateTransaction": {
                        "units": order["units"],
                        "takeProfitOnFill": payload["order"].get("takeProfitOnFill", {}),
                        "stopLossOnFill": payload["order"].get("stopLossOnFill", {}),
                    }
                },
            }
        }

    def OrderDetails_exe(self, order_id):
        order = self.orders.get(str(order_id))
        if order is None:
            return {"error": 0, "data": {"order": {"id": str(order_id), "state": "CANCELLED"}}}
        return {"error": 0, "data": {"order": order}}

    def TradeDetails_exe(self, trade_id):
        trade = self.trades.get(str(trade_id))
        if trade is None:
            return {"error": 0, "data": {"trade": {"id": str(trade_id), "state": "CLOSED"}}}
        return {"error": 0, "data": {"trade": trade}}

    def TradeClose_exe(self, trade_id, units=None):
        trade = self.trades.setdefault(
            str(trade_id),
            {
                "id": str(trade_id),
                "state": "OPEN",
                "price": "150.0",
                "currentUnits": "1000",
                "unrealizedPL": "0",
            },
        )
        trade["state"] = "CLOSED"
        trade["unrealizedPL"] = "0"
        trade["realizedPL"] = "0"
        return {"error": 0, "data": {"orderFillTransaction": {"tradeReduced": {"tradeID": str(trade_id)}}}}

    def OrderCancel_exe(self, order_id):
        if str(order_id) in self.orders:
            self.orders[str(order_id)]["state"] = "CANCELLED"
        return {"error": 0, "data": {"orderCancelTransaction": {"orderID": str(order_id)}}}

    def TradeCRCDO_exe(self, trade_id, data):
        self.crcdo_calls.append({"trade_id": trade_id, "data": data})
        return {"error": 0, "data": {"trade_id": str(trade_id)}}

    def OpenTrades_exe(self):
        return {"error": 0, "data": list(self.trades.values()), "json": {"trades": list(self.trades.values())}}

    def get_transaction_single(self, transaction_id):
        return {"error": 0, "data": {"id": str(transaction_id), "type": "ORDER_FILL"}}

    def OrderCancel_All_exe(self):
        for order in self.orders.values():
            order["state"] = "CANCELLED"
        return {"error": 0, "data": {"cancelled": list(self.orders)}}

    def TradeAllClose_exe(self):
        for trade in self.trades.values():
            trade["state"] = "CLOSED"
        return {"error": 0, "data": {"closed": list(self.trades)}}


class _LegacyCandleMetaStub:
    @staticmethod
    def cal_move_ave(_times):
        return 0


class _LegacyCandleAnalysisStub:
    candle_meta_class = _LegacyCandleMetaStub()


def _legacy_plan_summary(plan: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": plan.get("name"),
        "pair": plan.get("pair"),
        "type": plan.get("type"),
        "direction": plan.get("direction"),
        "units": plan.get("units"),
        "priority": plan.get("priority"),
        "target_price": plan.get("target_price"),
        "tp_price": plan.get("tp_price"),
        "lc_price": plan.get("lc_price"),
        "order_timeout_min": plan.get("order_timeout_min"),
        "trade_timeout_min": plan.get("trade_timeout_min"),
        "payload": (plan.get("for_api_json") or {}).get("order", {}),
    }


@contextlib.contextmanager
def _legacy_sandbox(scenario: DifferentialScenario):
    guard = _NetworkGuard()
    original_socket = socket.socket
    original_create_connection = socket.create_connection
    guard.install()

    fake_tokens = _build_tokens_stub()
    fake_notice = _build_notice_stub(fake_tokens)

    sys_modules_backup = dict(sys.modules)
    original_env = {
        "PYTHONDONTWRITEBYTECODE": os.environ.get("PYTHONDONTWRITEBYTECODE"),
        "PYTHONPATH": os.environ.get("PYTHONPATH"),
    }
    os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
    os.environ.pop("PYTHONPATH", None)

    sys.modules["tokens"] = fake_tokens
    sys.modules["send_notice"] = fake_notice

    imported = []
    try:
        import classOanda

        imported.append(classOanda)
        classOanda.Oanda = _LegacyFakeOanda

        import classCandleAnalysis
        import fLineAnalysis

        _reset_legacy_state(classCandleAnalysis, fLineAnalysis, fake_notice)

        yield _SandboxHandle(network_guard=guard, fake_notice=fake_notice)
    finally:
        guard.uninstall()
        socket.socket = original_socket
        socket.create_connection = original_create_connection
        for key, value in original_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        sys.modules.clear()
        sys.modules.update(sys_modules_backup)


def _assert_module_paths(modules: dict[str, types.ModuleType]) -> None:
    expected = os.environ.get("LEGACY_EXPECTED_WORKTREE")
    if not expected:
        return
    expected_root = Path(expected).resolve()
    for module_name, module in modules.items():
        module_file = Path(module.__file__).resolve()
        if expected_root not in module_file.parents:
            raise LegacyRunnerError(
                f"legacy module path mismatch for {module_name}: {module_file} is outside {expected_root}"
            )


class _SandboxHandle:
    def __init__(self, *, network_guard: "_NetworkGuard", fake_notice) -> None:
        self.network_guard = network_guard
        self.fake_notice = fake_notice

    def assert_no_network_calls(self) -> None:
        if self.network_guard.calls:
            raise LegacyRunnerError(f"Network call blocked: {self.network_guard.calls[0]}")


class _NetworkGuard:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self._original = None

    def install(self) -> None:
        import requests.sessions

        self._original = requests.sessions.Session.request

        def _blocked(session, method, url, *args, **kwargs):  # noqa: ANN001
            self.calls.append(f"requests:{method}:{url}")
            raise AssertionError("Network access is prohibited in legacy runner")

        requests.sessions.Session.request = _blocked

        def _blocked_socket(*args, **kwargs):  # noqa: ANN001
            self.calls.append("socket")
            raise AssertionError("Socket access is prohibited in legacy runner")

        socket.socket = _blocked_socket

        def _blocked_connection(*args, **kwargs):  # noqa: ANN001
            self.calls.append("socket.create_connection")
            raise AssertionError("Socket access is prohibited in legacy runner")

        socket.create_connection = _blocked_connection

    def uninstall(self) -> None:
        if self._original is None:
            return
        import requests.sessions

        requests.sessions.Session.request = self._original


def _build_tokens_stub() -> types.ModuleType:
    module = types.ModuleType("tokens")
    module.accountID = "test-practice-account"
    module.access_token = "test-practice-token"
    module.environment = "practice"
    module.accountIDl = "test-live-account"
    module.accountIDl2 = "test-live-account-2"
    module.access_tokenl = "test-live-token"
    module.environmentl = "practice"
    module.WEBHOOK_URL_usdyen = ""
    module.WEBHOOK_URL_eurousd = ""
    module.WEBHOOK_URL_audusd = ""
    module.WEBHOOK_URL_main = ""
    module.WEBHOOK_URL_friend = ""
    module.WEBHOOK_URL_inspection = ""
    module.folder_path = "/tmp"
    module.history_folder_path = "/tmp/"
    module.setting_json = {"l_units": 500, "hedge_close_on": False}

    def _line_send(*_args):
        return None

    module.line_send = _line_send
    return module


def _build_notice_stub(tokens_module: types.ModuleType) -> types.ModuleType:
    module = types.ModuleType("send_notice")
    module.tokens = tokens_module
    module.line_send_last_message = ""
    module.line_send_last_message_count = 0
    module.sent_messages = []

    def webhook_url_for_pair(pair):
        if pair == "AUD_USD":
            return ""
        if pair == "EUR_USD":
            return ""
        return ""

    def line_send(*args):
        module.sent_messages.append([str(item) for item in args])
        message = " ".join(str(item) for item in args)
        if module.line_send_last_message == message:
            module.line_send_last_message_count += 1
        else:
            module.line_send_last_message = message
            module.line_send_last_message_count = 1
        return 0

    module.webhook_url_for_pair = webhook_url_for_pair
    module.line_send = line_send
    return module


def _reset_legacy_state(classCandleAnalysis_module, fLineAnalysis_module, notice_module) -> None:
    candle_class = classCandleAnalysis_module.candleAnalysis
    candle_class.avoid_dup_5min_kara_time = 0
    candle_class.avoid_dup_5min_made_time = 0
    candle_class.latest_df_d5_df_r = None
    candle_class.latest_peaks_class = None
    candle_class.latest_candle_meta_class = None
    candle_class.latest_h1_df_r = None
    candle_class.latest_peaks_class_hour = None
    candle_class.latest_candle_meta_class_hour = None
    candle_class.latest_df_d30_df_r = None
    candle_class.latest_peaks_class_m30 = None
    candle_class.latest_candle_meta_class_m30 = None

    if hasattr(fLineAnalysis_module, "gl_previous_exe_df60_row"):
        fLineAnalysis_module.gl_previous_exe_df60_row = None
    if hasattr(fLineAnalysis_module, "gl_previous_exe_df60_order_time"):
        fLineAnalysis_module.gl_previous_exe_df60_order_time = None
    if hasattr(fLineAnalysis_module, "gl_previous_bb_h1_class"):
        fLineAnalysis_module.gl_previous_bb_h1_class = None
    if hasattr(fLineAnalysis_module, "gl_latest_trend_trigger_time"):
        fLineAnalysis_module.gl_latest_trend_trigger_time = None

    notice_module.line_send_last_message = ""
    notice_module.line_send_last_message_count = 0
    notice_module.sent_messages = []


def _legacy_frame_store(pair: str):
    return {
        "M5": _legacy_generate_frame(pair, periods=180, freq="5min"),
        "H1": _legacy_generate_frame(pair, periods=120, freq="1h"),
        "M30": _legacy_generate_frame(pair, periods=140, freq="30min"),
        "S5": _legacy_generate_frame(pair, periods=120, freq="5s"),
    }


def _legacy_generate_frame(pair: str, *, periods: int, freq: str):
    import pandas as pd

    is_jpy = pair.endswith("JPY")
    pip = 0.01 if is_jpy else 0.0001
    digits = 3 if is_jpy else 5
    base = 149.8 if is_jpy else 1.1

    times = pd.date_range(end=pd.Timestamp("2026-01-02 12:00:00"), periods=periods, freq=freq)
    rows = []
    for i, ts in enumerate(times):
        drift = ((i % 16) - 8) * pip
        close = round(base + drift, digits)
        open_price = round(close - ((i % 4) - 1) * pip, digits)
        high = round(max(open_price, close) + 2 * pip, digits)
        low = round(min(open_price, close) - 2 * pip, digits)
        inner_high = round(max(open_price, close), digits)
        inner_low = round(min(open_price, close), digits)
        body = round(close - open_price, digits)
        move = round(high - low, digits)
        rows.append(
            {
                "time_jp": ts.strftime("%Y/%m/%d %H:%M:%S"),
                "open": open_price,
                "close": close,
                "high": high,
                "low": low,
                "inner_high": inner_high,
                "inner_low": inner_low,
                "middle_price": round((inner_high + inner_low) / 2, digits),
                "middle_price_wick": round((high + low) / 2, digits),
                "mid_outer": round((high + low) / 2, digits),
                "body": body,
                "body_abs": abs(body),
                "direction": 1 if body > 0 else -1 if body < 0 else 0,
                "moves": move,
                "highlow": move,
                "up_rod": round(high - inner_high, digits),
                "low_rod": round(inner_low - low, digits),
                "RSI": float(40 + (i % 30)),
            }
        )

    frame = pd.DataFrame(rows).iloc[::-1].reset_index(drop=True)
    close_series = frame["close"]
    mean = close_series.rolling(window=30).mean()
    std = close_series.rolling(window=30).std()
    frame["bb_upper"] = mean + std * 2
    frame["bb_lower"] = mean - std * 2
    frame["bb_middle"] = ((frame["bb_lower"] + frame["bb_upper"]) / 2).round(digits)
    frame["bb_range"] = frame["bb_upper"] - frame["bb_lower"]
    return frame


def run_legacy_scenario_to_path(scenario: DifferentialScenario, output_path: Path, log_path: Path) -> None:
    result = run_legacy_scenario(scenario)
    output_path.write_text(json.dumps(result.trace, ensure_ascii=True), encoding="utf-8")
    log_path.write_text(result.log, encoding="utf-8")
