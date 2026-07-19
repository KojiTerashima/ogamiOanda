from __future__ import annotations

from dataclasses import dataclass

from ogami_oanda.domain.positions.models import OrderState, TradeState


@dataclass(frozen=True)
class LinkedPosition:
    position_id: str
    direction: int
    target_price: float
    stop_loss_range: float
    current_stop_loss: float
    order_state: OrderState
    trade_state: TradeState
    life: bool
    linkage_done: bool = False


@dataclass(frozen=True)
class LinkageCommand:
    action: str
    position_id: str
    stop_loss_price: float | None = None


@dataclass(frozen=True)
class LinkagePolicy:
    price_digits: int = 3

    def on_main_filled(self, linked_positions: list[LinkedPosition]) -> tuple[LinkageCommand, ...]:
        return tuple(
            LinkageCommand("cancel_order", position.position_id)
            for position in linked_positions
            if not position.linkage_done and position.order_state is OrderState.PENDING
        )

    def on_main_closed(
        self,
        *,
        main_direction: int,
        main_price_diff: float,
        linked_positions: list[LinkedPosition],
    ) -> tuple[LinkageCommand, ...]:
        if main_price_diff >= 0:
            return ()
        commands = []
        for position in linked_positions:
            if position.linkage_done or position.direction == main_direction:
                continue
            if not position.life or position.trade_state is not TradeState.OPEN:
                continue
            stop_loss = round(
                position.target_price - position.stop_loss_range * position.direction,
                self.price_digits,
            )
            commands.append(LinkageCommand("amend_stop_loss", position.position_id, stop_loss))
        return tuple(commands)
