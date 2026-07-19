import pytest

from ogami_oanda.application.ports.active_orders import ActiveOrderQuery
from ogami_oanda.application.services.portfolio import ActiveOrder, Portfolio
from ogami_oanda.domain.market.currency_pair import EUR_USD, USD_JPY


@pytest.mark.contract
def test_portfolio_implements_active_order_query_and_matches_by_pips():
    portfolio = Portfolio(USD_JPY, (ActiveOrder("existing", 1, 150.000, source="line", line_strategy="breakout"),))

    assert isinstance(portfolio, ActiveOrderQuery)
    assert portfolio.has_similar_active_order(1, 150.029, threshold_pips=3) is True
    assert portfolio.has_similar_active_order(1, 150.030, threshold_pips=3) is True
    assert portfolio.has_similar_active_order(1, 150.031, threshold_pips=3) is False


@pytest.mark.contract
def test_portfolio_filters_direction_source_and_strategy():
    portfolio = Portfolio(EUR_USD, (ActiveOrder("existing", -1, 1.10000, source="line", line_strategy="reversal"),))

    assert portfolio.has_similar_active_order(-1, 1.10029, source="line", line_strategy="reversal") is True
    assert portfolio.has_similar_active_order(1, 1.10000, source="line", line_strategy="reversal") is False
    assert portfolio.has_similar_active_order(-1, 1.10000, source="other", line_strategy="reversal") is False
    assert portfolio.has_similar_active_order(-1, 1.10000, source="line", line_strategy="breakout") is False
