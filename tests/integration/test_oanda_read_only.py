from __future__ import annotations

import pytest

from ogami_oanda.adapters.oanda.market_data import OandaMarketDataAdapter
from ogami_oanda.adapters.oanda.query import OandaQueryAdapter


pytestmark = pytest.mark.integration


def test_practice_account_summary_and_position_queries(practice_oanda_client):
    query = OandaQueryAdapter(practice_oanda_client)

    capabilities = query.account_capabilities()
    pending = query.pending_orders()
    opened = query.open_positions()

    assert capabilities.account_id == practice_oanda_client.account_id
    assert capabilities.last_transaction_id is not None
    assert isinstance(capabilities.hedging_enabled, bool)
    assert all(position.pair for position in pending)
    assert all(position.pair for position in opened)


@pytest.mark.parametrize("pair", ["USD_JPY", "EUR_USD", "AUD_USD"])
def test_practice_quotes_are_well_formed(practice_oanda_client, pair):
    quote = OandaMarketDataAdapter(practice_oanda_client).current_quote(pair)

    assert quote.pair == pair
    assert quote.bid > 0
    assert quote.ask >= quote.bid
    assert quote.bid <= quote.mid <= quote.ask


@pytest.mark.parametrize("pair", ["USD_JPY", "EUR_USD", "AUD_USD"])
@pytest.mark.parametrize("granularity", ["M5", "H1", "M30", "S5"])
def test_practice_candles_match_canonical_contract(
    practice_oanda_client,
    pair,
    granularity,
):
    frame = OandaMarketDataAdapter(practice_oanda_client).candles(
        pair,
        granularity,
        20,
    )

    assert len(frame) > 0
    assert frame["time_jp_dt"].is_monotonic_decreasing
    assert {"time_jp", "open", "close", "high", "low"}.issubset(frame.columns)
    assert (frame[["open", "close", "high", "low"]] > 0).all().all()
