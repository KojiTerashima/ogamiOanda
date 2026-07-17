import pandas as pd
import pandas.testing as pdt
import pytest

import classOanda as legacy_oanda
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
def test_domain_indicators_match_legacy_public_functions(pair_name):
    raw = _raw_candles()
    pair = currency_pair(pair_name)

    legacy = legacy_oanda.add_bb_data(legacy_oanda.add_ema_data(legacy_oanda.add_macd(legacy_oanda.add_rsi(legacy_oanda.add_basic_data(raw, pair)))), pair)
    domain = indicators.add_bb_data(indicators.add_ema_data(indicators.add_macd(indicators.add_rsi(indicators.add_basic_data(raw, pair)))), pair)

    pdt.assert_frame_equal(domain, legacy)
