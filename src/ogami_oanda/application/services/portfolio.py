from __future__ import annotations

from dataclasses import dataclass

from ogami_oanda.domain.market.currency_pair import CurrencyPair


@dataclass(frozen=True)
class ActiveOrder:
    name: str
    direction: int
    target_price: float
    source: str | None = None
    line_strategy: str | None = None


class Portfolio:
    def __init__(self, pair: CurrencyPair, active_orders: tuple[ActiveOrder, ...] = ()) -> None:
        self.pair = pair
        self.active_orders = active_orders

    def has_similar_active_order(
        self,
        direction: int,
        target_price: float,
        threshold_pips: float = 3,
        source: str | None = None,
        line_strategy: str | None = None,
    ) -> bool:
        for order in self.active_orders:
            if order.direction != direction:
                continue
            if source is not None and order.source != source:
                continue
            if line_strategy is not None and order.line_strategy != line_strategy:
                continue
            if abs(self.pair.price_to_pips(target_price - order.target_price)) <= threshold_pips:
                return True
        return False
