import classOrderCreate as OCreate


def create_trend_market_order(
    *,
    name: str,
    latest_price: float,
    direction: int,
    tp: float,
    lc: float,
    lc_change,
    units: float,
    priority: int,
    decision_time,
    candle_analysis_class,
    lc_change_candle_type: str,
):
    return OCreate.Order(
        {
            "name": name,
            "current_price": latest_price,
            "target": 0,
            "direction": direction,
            "type": "MARKET",
            "tp": tp,
            "lc": lc,
            "lc_change": lc_change,
            "units": units,
            "priority": priority,
            "decision_time": decision_time,
            "candle_analysis_class": candle_analysis_class,
            "lc_change_candle_type": lc_change_candle_type,
        }
    )
