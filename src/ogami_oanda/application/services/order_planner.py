from __future__ import annotations

from ogami_oanda.domain.market.currency_pair import currency_pair
from ogami_oanda.domain.orders.models import (
    BrokerOrderRequest,
    OrderContext,
    OrderIntent,
    OrderPlan,
    OrderType,
)


class OrderPlanner:
    def plan(self, intent: OrderIntent, context: OrderContext) -> OrderPlan:
        pair = currency_pair(intent.pair)
        direction = intent.direction.value
        target_price = self._target_price(intent, context)
        take_profit_price = self._protection_price(intent.take_profit, intent.take_profit_is_price, target_price, direction, pair)
        stop_loss_price = self._protection_price(intent.stop_loss, intent.stop_loss_is_price, target_price, -direction, pair)
        broker_request = BrokerOrderRequest(
            instrument=intent.pair,
            units=intent.units * direction,
            order_type=intent.order_type,
            price=target_price,
            take_profit_price=take_profit_price,
            stop_loss_price=stop_loss_price,
        )
        return OrderPlan(
            intent=intent,
            context=context,
            target_price=target_price,
            take_profit_price=take_profit_price,
            stop_loss_price=stop_loss_price,
            take_profit_range=pair.round_price(abs(take_profit_price - target_price)),
            stop_loss_range=pair.round_price(abs(stop_loss_price - target_price)),
            broker_request=broker_request,
        )

    @staticmethod
    def _target_price(intent: OrderIntent, context: OrderContext) -> float:
        pair = currency_pair(intent.pair)
        if intent.order_type is OrderType.MARKET:
            return pair.round_price(context.current_price)
        if intent.target_is_price:
            return pair.round_price(intent.target)
        target_direction = intent.direction.value if intent.order_type is OrderType.STOP else -intent.direction.value
        return pair.round_price(context.current_price + intent.target * target_direction)

    @staticmethod
    def _protection_price(value: float, is_price: bool, target_price: float, direction: int, pair) -> float:
        return pair.round_price(value if is_price else target_price + value * direction)
