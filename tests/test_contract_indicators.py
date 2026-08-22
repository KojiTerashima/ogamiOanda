import pandas as pd
import pytest

import classOanda
from ogami_oanda.adapters.oanda.mappers import map_candle_response
from ogami_oanda.domain.analysis import indicators
from ogami_oanda.domain.market.currency_pair import currency_pair


def _raw_candles() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "time": f"2026-01-02T00:{minute:02d}:00.000000000Z",
                "complete": True,
                "mid": {"o": str(150 + minute / 100), "c": str(150 + (minute + 1) / 100), "h": str(150 + (minute + 2) / 100), "l": str(150 + minute / 100 - 0.01)},
            }
            for minute in range(35)
        ]
    )


@pytest.mark.contract
@pytest.mark.parametrize("pair_name", ["USD_JPY", "EUR_USD", "AUD_USD"])
def test_domain_indicators_enrich_canonical_candles_without_oanda_fields(pair_name):
    raw = _raw_candles()
    pair = currency_pair(pair_name)

    canonical = map_candle_response({"candles": raw.to_dict("records")})
    canonical = indicators.add_basic_data(canonical, pair).sort_values("time", ascending=True).reset_index(drop=True)
    domain = indicators.add_bb_data(indicators.add_ema_data(indicators.add_macd(indicators.add_rsi(canonical))), pair)

    assert {"mid", "ask", "bid", "complete"}.isdisjoint(domain.columns)
    assert domain.iloc[0]["open"] == 150.0
    assert domain.iloc[0]["close"] == 150.01
    assert domain.iloc[0]["body"] == pytest.approx(0.01)
    assert domain.iloc[0]["inner_high"] == 150.01
    assert domain.iloc[0]["inner_low"] == 150.0
    assert domain.iloc[-1]["RSI"] > 90
    assert pd.notna(domain.iloc[-1]["bb_range"])


@pytest.mark.contract
def test_root_oanda_indicator_facade_keeps_raw_candle_compatibility():
    raw = pd.DataFrame(
        [
            {
                "time_jp": "2026/01/02 09:00:00",
                "time": "2026-01-02T00:00:00.000000000Z",
                "complete": True,
                "volume": 1,
                "mid": {
                    "o": "150.0",
                    "c": "150.1",
                    "h": "150.2",
                    "l": "149.9",
                },
            }
        ]
    )

    enriched = classOanda.add_basic_data(raw, currency_pair("USD_JPY"))

    assert enriched.iloc[0][["open", "close", "high", "low"]].to_dict() == {
        "open": 150.0,
        "close": 150.1,
        "high": 150.2,
        "low": 149.9,
    }
    assert "mid" not in enriched
    assert "complete" not in enriched
