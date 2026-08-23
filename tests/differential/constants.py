from __future__ import annotations

from pathlib import Path

BASELINE_COMMIT = "eff331c2367570dcb8bc35a323a382e8255eda7b"
BASELINE_TREE = "7dc341e37b663e7f206736abfe001e81fe74dd6a"
TRACE_SCHEMA_VERSION = "1.1.0"
SCENARIO_SCHEMA_VERSION = "1.0.0"

REQUIRED_BASELINE_FILES = (
    "main_exe.py",
    "fAnalysis_order_Main.py",
    "fLineAnalysis.py",
    "classOrderCreate.py",
    "classPosition.py",
    "classPositionControl.py",
    "classOanda.py",
)

DIFFERENTIAL_ROOT = Path(__file__).resolve().parent
SCENARIO_ROOT = DIFFERENTIAL_ROOT / "scenarios"
GOLDEN_ROOT = DIFFERENTIAL_ROOT / "golden" / BASELINE_COMMIT
ALLOWLIST_PATH = DIFFERENTIAL_ROOT / "intentional_deltas.json"
ARTIFACT_ROOT = Path("build") / "differential"

LEGACY_TOKENS_REQUIRED = (
    "accountID",
    "access_token",
    "environment",
    "accountIDl",
    "accountIDl2",
    "access_tokenl",
    "environmentl",
    "WEBHOOK_URL_usdyen",
    "WEBHOOK_URL_eurousd",
    "WEBHOOK_URL_audusd",
    "WEBHOOK_URL_main",
    "WEBHOOK_URL_friend",
    "WEBHOOK_URL_inspection",
    "folder_path",
    "history_folder_path",
    "setting_json",
    "line_send",
)

# Strings are checked in baseline source files as a fail-closed contract.
REQUIRED_BASELINE_SYMBOL_SNIPPETS: dict[str, tuple[str, ...]] = {
    "main_exe.py": (
        "class main():",
        "def exe_manage(self):",
        "def mode1(self):",
        "def mode2(self):",
        "def run(pair=None):",
    ),
    "fAnalysis_order_Main.py": (
        "class wrap_all_analysis():",
        "def wrap_all_inspections(self, mode=\"inspection\"):",
    ),
    "fLineAnalysis.py": (
        "class LineOrderCoordinator:",
        "def build_line_candidates(",
        "def select_line_candidates(",
        "def create_orders_from_candidates(",
    ),
    "classOrderCreate.py": (
        "class Order:",
        "def order_finalize_new(self):",
        "def make_json_from_instance(self):",
    ),
    "classPosition.py": (
        "class order_information:",
        "def order_plan_registration(self, order_class):",
        "def update_information(self, candle_analysis_class=None):",
        "def watching_for_position(self, candle_analysis_class):",
    ),
    "classPositionControl.py": (
        "class position_control:",
        "def order_class_add(self, order_classes):",
        "def all_update_information(self, candle_analysis_class=None):",
        "def catch_up_position_and_del_order(self):",
    ),
    "classOanda.py": (
        "class Oanda:",
        "def NowPrice_exe(self, instrument):",
        "def InstrumentsCandles_multi_exe(self, pair, params, roop):",
    ),
}
