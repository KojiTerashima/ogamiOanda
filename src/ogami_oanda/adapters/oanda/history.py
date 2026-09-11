"""OANDA read-only five-second Mid/Bid/Ask history acquisition."""

from datetime import datetime, timedelta

from oandapyV20.endpoints.instruments import InstrumentsCandles

from ogami_oanda.adapters.oanda.client import OandaClient
from ogami_oanda.application.errors import (
    ExternalServiceAuthorizationError,
    TransientExternalServiceError,
)
from ogami_oanda.domain.market.history import HistoricalCandle, OHLC, utc_time


class OandaHistorySource:
    def __init__(self, client: OandaClient) -> None:
        self.client = client

    def fetch(self, pair: str, start: datetime, end: datetime) -> list[HistoricalCandle]:
        start, end = utc_time(start), utc_time(end)
        if not timedelta(0) < end - start <= timedelta(hours=6):
            raise ValueError("historical candle request must be positive and at most six hours")
        try:
            response = self.client.request(InstrumentsCandles(instrument=pair, params={
                "granularity": "S5", "price": "MBA", "from": start.isoformat(),
                "to": end.isoformat(), "smooth": False, "includeFirst": True,
            }))
        except ExternalServiceAuthorizationError:
            raise
        except TransientExternalServiceError as error:
            raise TransientExternalServiceError(
                "oanda", "historical candle request temporarily unavailable",
                retry_after_seconds=error.retry_after_seconds,
            ) from None
        except Exception:
            raise ValueError("historical candle request failed") from None
        try:
            rows = response["candles"]
            if not isinstance(rows, list) or len(rows) > 4321:
                raise ValueError
            result = []
            previous = None
            for row in rows:
                at = utc_time(row["time"])
                # Some endpoint responses include the exclusive end boundary.
                if at == end:
                    continue
                if not start <= at < end or row.get("complete") is not True:
                    raise ValueError
                if previous is not None and at <= previous:
                    raise ValueError
                previous = at
                values = [OHLC(*(float(row[component][key]) for key in ("o", "h", "l", "c")))
                          for component in ("mid", "bid", "ask")]
                volume = row.get("volume", 0)
                if type(volume) is not int:
                    raise ValueError
                result.append(HistoricalCandle(at, *values, volume=volume))
            return result
        except (KeyError, TypeError, ValueError, AttributeError, OverflowError):
            raise ValueError("malformed historical candle response") from None
