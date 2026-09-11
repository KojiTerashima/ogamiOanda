"""Explicit conversion of upstream resolved prices to the existing order API."""

from __future__ import annotations

from ogami_oanda.domain.orders.models import Direction, OrderIntent, OrderType


def to_order_intents(candidates):
    """Translate executable candidates using explicit absolute-price flags."""
    intents = []
    for candidate in candidates:
        if candidate.execution != "ready":
            continue
        metadata = dict(candidate.metadata)
        metadata["legacy_plan_metadata"] = dict(candidate.metadata)
        metadata["name_ymdhms"] = metadata.get("name_ymdhms", candidate.name)
        intents.append(OrderIntent(
            pair=candidate.pair, direction=Direction(candidate.direction),
            order_type=OrderType(candidate.order_type),
            target=candidate.target_price, target_is_price=True,
            take_profit=candidate.take_profit_price, take_profit_is_price=True,
            stop_loss=candidate.stop_loss_price, stop_loss_is_price=True,
            units=candidate.units, name=candidate.name, priority=candidate.priority,
            order_timeout_min=candidate.order_timeout_min,
            trade_timeout_min=candidate.trade_timeout_min,
            lc_change=candidate.lc_change, metadata=metadata,
        ))
    return tuple(intents)
