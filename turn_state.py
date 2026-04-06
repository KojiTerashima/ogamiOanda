class AnalysisRuntimeState:
    def __init__(self):
        self.line_send_enabled = False
        self.previous_exe_df60_row = None
        self.previous_exe_df60_order_time = None
        self.previous_bb_h1_class = None
        self.latest_trend_trigger_time = None
        self.units_std = 1  # OrderCreateのベーシックUnitは10000ドル。それにかける倍率


runtime_state = AnalysisRuntimeState()
