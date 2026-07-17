from types import SimpleNamespace

import pandas as pd
import pytest

from classCandleAnalysis import CandleMeta as LegacyCandleMeta
from ogami_oanda.domain.analysis.candle_meta import CandleMeta
from ogami_oanda.domain.market.currency_pair import currency_pair


def _peaks_class():
    frame = pd.DataFrame(
        {
            "body_abs": [0.12, 0.08, 0.04, 0.02, 0.01],
            "inner_high": [150.2, 150.1, 150.05, 150.03, 150.02],
            "inner_low": [150.0, 149.95, 149.9, 149.85, 149.8],
            "highlow": [0.2, 0.15, 0.1, 0.08, 0.05],
        }
    )
    return SimpleNamespace(
        df_r_original=frame,
        pair=currency_pair("USD_JPY"),
        peaks_original=[
            {"count": 2, "gap": 0.1, "peak": 150.1},
            {"count": 3, "gap": 0.31, "peak": 149.9},
        ],
        is_big_move_peak=False,
    )


@pytest.mark.contract
@pytest.mark.parametrize("granularity", ["M5", "M30", "H1"])
def test_domain_candle_meta_matches_legacy_public_class(granularity):
    legacy = LegacyCandleMeta(_peaks_class(), granularity)
    domain = CandleMeta(_peaks_class(), granularity)

    for attribute in ("recent_fluctuation_range", "ave_move", "ave_move_for_lc", "is_big_move_candle"):
        assert getattr(domain, attribute) == getattr(legacy, attribute)
    assert domain.cal_move_ave(2) == legacy.cal_move_ave(2)
