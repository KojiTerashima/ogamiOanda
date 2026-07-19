import pandas as pd
import pytest

import classCandleAnalysis


@pytest.mark.characterization
@pytest.mark.parametrize("pair_name", ["USD_JPY", "EUR_USD", "AUD_USD"])
def test_offline_analysis_fixture_frames_match_contract(pair_name, analysis_frame_store):
    frames = analysis_frame_store[pair_name]
    required_columns = {
        "time_jp",
        "time_jp_dt",
        "open",
        "close",
        "high",
        "low",
        "inner_high",
        "inner_low",
        "body",
        "body_abs",
        "moves",
        "highlow",
        "middle_price",
        "mid_outer",
        "RSI",
        "bb_range",
    }

    for timeframe in ("M5", "H1", "M30", "S5"):
        frame = frames[timeframe]
        assert required_columns <= set(frame.columns)
        assert frame["time_jp_dt"].is_monotonic_decreasing
        assert frame.iloc[0]["time_jp_dt"] > frame.iloc[-1]["time_jp_dt"]
        assert frame.iloc[0]["time_jp"] == frame.iloc[0]["time_jp_dt"].strftime("%Y/%m/%d %H:%M:%S")

    candle = classCandleAnalysis.candleAnalysis(
        None,
        pair_name,
        0,
        m5_df_r=frames["M5"].copy(),
        h1_df_r=frames["H1"].copy(),
        m30_df_r=frames["M30"].copy(),
        current_price=float(frames["M5"].iloc[1]["close"]),
    )

    assert isinstance(candle.d5_df_r, pd.DataFrame)
    assert len(candle.peaks_class.peaks_original) >= 3
    assert len(candle.peaks_class_hour.peaks_original) >= 3
    assert len(candle.peaks_class_m30.peaks_original) >= 3
