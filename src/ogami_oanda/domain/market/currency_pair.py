from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CurrencyPair:
    name: str
    pip_value: float
    round_keta: int
    price_min: float
    price_max: float
    spread_limit_pips: float

    def round_price(self, price: float) -> float:
        return round(price, self.round_keta)

    def price_to_str(self, price: float) -> str:
        return str(self.round_price(price))

    def pips_to_price(self, pips: float) -> float:
        return self.round_price(pips * self.pip_value)

    def price_to_pips(self, price_diff: float) -> float:
        return round(price_diff / self.pip_value, 2)

    def is_price(self, value: float) -> bool:
        return self.price_min <= float(value) <= self.price_max


USD_JPY = CurrencyPair("USD_JPY", 0.01, 3, 80, 200, 1.1)
EUR_USD = CurrencyPair("EUR_USD", 0.0001, 5, 0.5, 2.0, 1.5)
AUD_USD = CurrencyPair("AUD_USD", 0.0001, 5, 0.3, 1.5, 1.8)

_CURRENCY_PAIRS = {pair.name: pair for pair in (USD_JPY, EUR_USD, AUD_USD)}


def currency_pair(pair_name: str) -> CurrencyPair:
    try:
        return _CURRENCY_PAIRS[pair_name]
    except KeyError as error:
        raise ValueError(f"Unsupported currency pair: {pair_name}") from error
