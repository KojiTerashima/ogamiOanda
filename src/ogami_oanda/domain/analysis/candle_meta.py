from __future__ import annotations


class CandleMeta:
    def __init__(self, peaks_class, granularity: str) -> None:
        self.df_r = peaks_class.df_r_original
        self.peaks_class = peaks_class
        self.pair = peaks_class.pair
        self.u = self.pair.round_keta
        self.ave_move = 0
        self.ave_move_for_lc = 0
        self.dependence_large_body_criteria = self.pair.pips_to_price(10)
        self.recent_fluctuation_range = 0
        self.fluctuation_gap = self.pair.pips_to_price(30)
        self.fluctuation_count = 3
        self.is_big_move_candle = False
        self.cal_move_size()

    def cal_move_size(self) -> None:
        filtered_frame = self.df_r[:65]
        sorted_frame = filtered_frame.sort_values(by="body_abs", ascending=False)
        self.recent_fluctuation_range = round(sorted_frame["inner_high"].max() - sorted_frame["inner_low"].min(), self.u)
        self.ave_move = filtered_frame.head(5)["highlow"].mean()
        self.ave_move_for_lc = self.ave_move * 1.6

        target_peak = self.peaks_class.peaks_original[0] if len(self.peaks_class.peaks_original) == 1 else self.peaks_class.peaks_original[1]
        if self.peaks_class.peaks_original[0]["count"] == 2:
            self.peaks_class.is_big_move_peak = (
                target_peak["gap"] >= self.fluctuation_gap and target_peak["count"] <= self.fluctuation_count
            )

        recent_frame = self.peaks_class.df_r_original[:5]
        self.is_big_move_candle = recent_frame.sort_values(by="body_abs", ascending=False)["body_abs"].max() >= self.dependence_large_body_criteria

    def cal_move_ave(self, times: float) -> float:
        self.ave_move = self.peaks_class.df_r_original[:65].head(9)["highlow"].mean()
        self.ave_move_for_lc = self.ave_move * times
        return self.ave_move_for_lc
