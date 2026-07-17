from __future__ import annotations

import oandapyV20.endpoints.instruments as instruments
from oandapyV20.endpoints.pricing import PricingInfo

from ogami_oanda.adapters.oanda.client import OandaClient
from ogami_oanda.adapters.oanda.mappers import map_candle_response, map_price_response


class OandaMarketDataAdapter:
    def __init__(self, client: OandaClient) -> None:
        self.client = client

    def current_price(self, pair: str) -> float:
        response = self.client.request(PricingInfo(accountID=self.client.account_id, params={"instruments": pair}))
        return map_price_response(pair, response)["mid"]

    def current_price_details(self, pair: str) -> dict[str, float]:
        response = self.client.request(PricingInfo(accountID=self.client.account_id, params={"instruments": pair}))
        return map_price_response(pair, response)

    def candles(self, pair: str, granularity: str, count: int):
        response = self.client.request(instruments.InstrumentsCandles(instrument=pair, params={"granularity": granularity, "count": count}))
        return map_candle_response(response)
