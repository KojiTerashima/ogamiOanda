import pandas as pd
import pytest

from ogami_oanda.application.services.market_analysis_service import (
    MarketAnalysisService,
)
from ogami_oanda.application.services.portfolio import ActiveOrder, Portfolio
from ogami_oanda.domain.market.currency_pair import currency_pair
from ogami_oanda.domain.orders.models import Direction
from tests.fakes import FakeMarketData


def _frame():
    times = pd.date_range("2026-01-02 01:00:00", periods=40, freq="-5min")
    close = [150 + index * 0.01 for index in range(40)]
    return pd.DataFrame({
        "time_jp": [value.strftime("%Y/%m/%d %H:%M:%S") for value in times],
        "open": close,
        "close": [value + 0.005 for value in close],
        "high": [value + 0.02 for value in close],
        "low": [value - 0.02 for value in close],
        "inner_high": [value + 0.005 for value in close],
        "inner_low": close,
    })


@pytest.mark.contract
def test_market_analysis_builds_intents_from_validated_market_frames():
    frame = _frame()
    market_data = FakeMarketData({("USD_JPY", granularity): frame for granularity in ("M5", "H1", "M30", "S5")}, {"USD_JPY": 150.4})
    service = MarketAnalysisService(
        market_data,
        lambda context, price: [{"direction": 1, "target_price": 150.3, "line_strategy": "test", "lc_pips": 10, "tp_pips": 20, "order_timeout_min": 15}],
    )

    result = service.analyze("USD_JPY", "2026/01/02 01:00:00")

    assert len(result.intents) == 1
    assert result.intents[0].direction is Direction.BUY
    assert result.intents[0].metadata["line_strategy"] == "test"
    assert set(result.peaks) == {"M5", "H1", "M30"}


@pytest.mark.contract
def test_market_analysis_excludes_matching_active_line_orders():
    frame = _frame()
    market_data = FakeMarketData({("USD_JPY", granularity): frame for granularity in ("M5", "H1", "M30", "S5")}, {"USD_JPY": 150.4})
    portfolio = Portfolio(currency_pair("USD_JPY"), (ActiveOrder("existing", 1, 150.3, "line", "test"),))
    service = MarketAnalysisService(market_data, lambda context, price: [{"direction": 1, "target_price": 150.3, "line_strategy": "test"}], portfolio)

    assert service.analyze("USD_JPY", "2026/01/02 01:00:00").intents == ()
