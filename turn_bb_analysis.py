import turn_analysis_core as ta_core


def latest_price_position_from_bounds(bb_upper: float, bb_lower: float, price: float) -> int:
    return ta_core.latest_price_position_in_bb(bb_upper, bb_lower, price)


def latest_price_position_from_row(row) -> int:
    return latest_price_position_from_bounds(row["bb_upper"], row["bb_lower"], row["close"])


def latest_price_position_from_df(df_r) -> int:
    latest = df_r.iloc[0]
    return latest_price_position_from_bounds(latest["bb_upper"], latest["bb_lower"], latest["close"])
