from __future__ import annotations

from ogami_oanda.domain.positions.models import OrderState, PositionSnapshot, TradeState


def _order_state(state: object, waiting: bool) -> OrderState:
    if waiting:
        return OrderState.WATCHING
    normalized = str(state or "").upper()
    return {
        "PENDING": OrderState.PENDING,
        "FILLED": OrderState.FILLED,
        "CANCELLED": OrderState.CANCELLED,
        "REJECTED": OrderState.REJECTED,
    }.get(normalized, OrderState.REGISTERED)


def _trade_state(state: object) -> TradeState:
    return {
        "OPEN": TradeState.OPEN,
        "CLOSED": TradeState.CLOSED,
    }.get(str(state or "").upper(), TradeState.NONE)


def legacy_position_to_snapshot(position: object) -> PositionSnapshot:
    waiting = bool(getattr(position, "waiting_order", False))
    return PositionSnapshot(
        name=str(getattr(position, "name", "")),
        pair=str(getattr(position, "pair", "USD_JPY")),
        order_state=_order_state(getattr(position, "o_state", ""), waiting),
        trade_state=_trade_state(getattr(position, "t_state", "")),
        order_id=str(getattr(position, "o_id", "")) or None,
        trade_id=str(getattr(position, "t_id", "")) or None,
        life=bool(getattr(position, "life", False)),
        waiting_order=waiting,
    )


def snapshot_to_legacy_position(snapshot: PositionSnapshot) -> dict[str, object]:
    return {
        "name": snapshot.name,
        "pair": snapshot.pair,
        "o_state": snapshot.order_state.value,
        "t_state": snapshot.trade_state.value,
        "o_id": snapshot.order_id or 0,
        "t_id": snapshot.trade_id or 0,
        "life": snapshot.life,
        "waiting_order": snapshot.waiting_order,
    }