from datetime import datetime, timedelta, timezone

import pytest


def test_s5_model_validates_prices_and_timestamp():
    from ogami_oanda.domain.market.history import HistoricalCandle, OHLC

    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    price = OHLC(150, 151, 149, 150.5)
    candle = HistoricalCandle(start, price, price, price)
    assert candle.end == start + timedelta(seconds=5)
    with pytest.raises(ValueError):
        OHLC(150, 149, 151, 150)
    with pytest.raises(ValueError):
        HistoricalCandle(start.replace(tzinfo=None), price, price, price)
    with pytest.raises(ValueError):
        HistoricalCandle(start, price, OHLC(151, 152, 150, 151.5), price)


def test_market_aggregates_only_observed_prices_and_bounds_window():
    from ogami_oanda.application.services.historical_market import HistoricalMarket
    from ogami_oanda.domain.market.history import HistoricalCandle, OHLC

    market = HistoricalMarket("USD_JPY", {"M1": 3, "S5": 3})
    start = datetime(2024, 1, 2, tzinfo=timezone.utc)
    for i in range(37):
        price = 150 + i / 100
        p = OHLC(price, price + .001, price - .001, price)
        market.advance(HistoricalCandle(start + timedelta(seconds=5 * i), p, p, p))
    frame = market.candles("USD_JPY", "M1", 3)
    assert len(frame) == 3
    assert frame.iloc[0]["complete"] == False  # noqa: E712
    assert frame.iloc[1]["complete"] == True  # noqa: E712
    assert frame.iloc[0]["high"] == pytest.approx(150.361)
    assert frame.iloc[1]["close"] == pytest.approx(150.35)
    assert market.current_quote("USD_JPY").source_time == start + timedelta(seconds=185)
    assert market.ready
    assert market.buffered_candles <= 8


def test_future_prices_cannot_change_earlier_market_snapshot():
    from ogami_oanda.application.services.historical_market import HistoricalMarket
    from ogami_oanda.domain.market.history import HistoricalCandle, OHLC

    market = HistoricalMarket("USD_JPY", {"M1": 2})
    start = datetime(2024, 1, 2, tzinfo=timezone.utc)
    p = OHLC(150, 150, 150, 150)
    market.advance(HistoricalCandle(start, p, p, p))
    before = market.candles("USD_JPY", "M1", 2)
    future = OHLC(190, 195, 185, 192)
    market.advance(HistoricalCandle(start + timedelta(seconds=5), future, future, future))
    assert before.iloc[0]["high"] == 150
    assert market.candles("USD_JPY", "M1", 2).iloc[0]["high"] == 195


def test_market_rejects_duplicates_and_records_gaps_without_padding():
    from ogami_oanda.application.services.historical_market import HistoricalMarket
    from ogami_oanda.domain.market.history import HistoricalCandle, OHLC

    market = HistoricalMarket("USD_JPY", {"M1": 3})
    start = datetime(2024, 1, 2, tzinfo=timezone.utc)
    p = OHLC(150, 150, 150, 150)
    first = HistoricalCandle(start, p, p, p)
    market.advance(first)
    with pytest.raises(ValueError, match="order"):
        market.advance(first)
    market.advance(HistoricalCandle(start + timedelta(days=3), p, p, p))
    assert market.gap_count == 1
    assert len(market.candles("USD_JPY", "M1", 3)) == 2


def test_quote_only_strategy_needs_no_candle_windows():
    from ogami_oanda.application.services.historical_market import HistoricalMarket
    from ogami_oanda.domain.market.history import HistoricalCandle, OHLC

    market = HistoricalMarket("USD_JPY", {})
    assert not market.ready
    p = OHLC(150, 150, 150, 150)
    market.advance(HistoricalCandle(datetime(2024, 1, 2, tzinfo=timezone.utc), p, p, p))
    assert market.ready
    assert market.buffered_candles == 0


def test_small_window_boundary_does_not_count_synthetic_placeholder_as_warmup():
    from ogami_oanda.application.services.historical_market import HistoricalMarket
    from ogami_oanda.domain.market.history import HistoricalCandle, OHLC

    market = HistoricalMarket("USD_JPY", {"S5": 1})
    p = OHLC(150, 150, 150, 150)
    market.advance(HistoricalCandle(datetime(2024, 1, 2, tzinfo=timezone.utc), p, p, p))
    assert market.ready


@pytest.mark.parametrize("granularity,seconds", [("S5", 5), ("M1", 60), ("M5", 300), ("M30", 1800), ("H1", 3600)])
def test_market_snapshots_survive_rollover_sparse_queries_and_plugin_edits(granularity, seconds):
    from ogami_oanda.application.services.historical_market import HistoricalMarket
    from ogami_oanda.domain.market.history import HistoricalCandle, OHLC

    market = HistoricalMarket("USD_JPY", {granularity: 3})
    start = datetime(2024, 1, 2, tzinfo=timezone.utc)
    snapshots = []
    for index in range(8):
        value = 150 + index
        price = OHLC(value, value, value, value)
        # Observe each boundary, including the current-price-only placeholder.
        at = start + timedelta(seconds=(index + 1) * seconds - 5)
        market.advance(HistoricalCandle(at, price, price, price))
        if index == 4:
            continue  # A skipped query must not leave a stale cached row.
        frame = market.candles("USD_JPY", granularity, 3)
        assert frame.iloc[0]["close"] == value
        assert frame.iloc[1]["close"] == value
        assert not frame.iloc[0]["complete"]
        assert frame.iloc[1]["complete"]
        snapshots.append((frame, value))
        edited = market.candles("USD_JPY", granularity, 1)
        edited.loc[0, "close"] = 999
        assert market.candles("USD_JPY", granularity, 1).iloc[0]["close"] == value
    assert all(frame.iloc[0]["close"] == value for frame, value in snapshots)
