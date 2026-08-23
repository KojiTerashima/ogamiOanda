from __future__ import annotations

import hashlib
from collections.abc import Iterable, Mapping

from ogami_oanda.domain.market.currency_pair import currency_pair
from ogami_oanda.domain.orders.models import (
    BrokerOrderRequest,
    Direction,
    OrderContext,
    OrderIntent,
    OrderPlan,
    OrderType,
    submission_fingerprint,
)


class LegacyOrderView:
    """Compatibility view consumed by the root Position registration API."""

    def __init__(self, exe_order_plan: dict[str, object], current_price: float) -> None:
        self.exe_order_plan = exe_order_plan
        self.current_price = float(current_price)
        self.name = str(exe_order_plan["name"])
        self.name_ymdhms = str(exe_order_plan["name_ymdhms"])
        self.oa_mode = int(exe_order_plan["oa_mode"])
        self.lc_change = list(exe_order_plan.get("lc_change", []))
        self.linkage_order_classes: list[LegacyOrderView] = []


def _legacy_bool(value: object, *, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"false", "0", "no", "off"}:
            return False
        if normalized in {"true", "1", "yes", "on"}:
            return True
    return bool(value)


def _order_name(value: object) -> str | None:
    if isinstance(value, str):
        return value or None
    if isinstance(value, Mapping):
        name = value.get("name")
        return str(name) if name else None
    name = getattr(value, "name", None)
    if name:
        return str(name)
    plan = getattr(value, "exe_order_plan", None)
    if isinstance(plan, Mapping) and plan.get("name"):
        return str(plan["name"])
    return None


def _order_names(value: object) -> set[str]:
    if value is None:
        return set()
    if isinstance(value, (str, Mapping)):
        name = _order_name(value)
        return {name} if name else set()
    if isinstance(value, Iterable):
        return {
            name
            for item in value
            if (name := _order_name(item)) is not None
        }
    name = _order_name(value)
    return {name} if name else set()


def _legacy_linkage(order: object, plan: Mapping[str, object]) -> tuple[str | None, set[str]]:
    explicit_id = plan.get("linkage_id", getattr(order, "linkage_id", None))
    related_names: set[str] = set()
    for key in (
        "linkage_order_classes",
        "linkage_order_names",
        "linked_order_names",
        "linkage_names",
    ):
        related_names.update(_order_names(plan.get(key)))
        related_names.update(_order_names(getattr(order, key, None)))

    linkage = plan.get("linkage", getattr(order, "linkage", None))
    if isinstance(linkage, Mapping):
        explicit_id = explicit_id or linkage.get("linkage_id") or linkage.get("id")
        for key in ("orders", "names", "linkage_order_names"):
            related_names.update(_order_names(linkage.get(key)))
    else:
        related_names.update(_order_names(linkage))
    return (str(explicit_id) if explicit_id else None), related_names


def _derived_linkage_id(pair: str, names: set[str]) -> str:
    identity = "\x1f".join((pair, *sorted(names)))
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:16]
    return f"legacy-linkage-{digest}"


def legacy_orders_to_order_plans(order_classes: Iterable[object]) -> list[OrderPlan]:
    """Convert a legacy order batch without losing object linkage relationships."""
    records: list[tuple[object, dict[str, object], str, str, str | None]] = []
    adjacency: dict[str, set[str]] = {}
    explicit_groups: dict[str, set[str]] = {}

    for order in order_classes:
        plan = dict(getattr(order, "exe_order_plan"))
        name = str(plan["name"])
        pair = str(plan["pair"])
        explicit_id, related_names = _legacy_linkage(order, plan)
        related_names.discard(name)
        adjacency.setdefault(name, set()).update(related_names)
        for related_name in related_names:
            adjacency.setdefault(related_name, set()).add(name)
        if explicit_id is not None:
            explicit_groups.setdefault(explicit_id, set()).add(name)
        records.append((order, plan, name, pair, explicit_id))

    for names in explicit_groups.values():
        for name in names:
            adjacency.setdefault(name, set()).update(names - {name})

    components: dict[str, set[str]] = {}
    for name in adjacency:
        if name in components:
            continue
        component: set[str] = set()
        pending = [name]
        while pending:
            current = pending.pop()
            if current in component:
                continue
            component.add(current)
            pending.extend(adjacency.get(current, ()) - component)
        for component_name in component:
            components[component_name] = component

    result = []
    for order, plan, name, pair, explicit_id in records:
        component = components.get(name, {name})
        component_ids = sorted(
            candidate_id
            for candidate_id, names in explicit_groups.items()
            if names & component
        )
        linkage_id = explicit_id
        if len(component_ids) == 1:
            linkage_id = component_ids[0]
        elif len(component_ids) > 1 or len(component) > 1:
            linkage_id = _derived_linkage_id(pair, component)

        metadata_overrides: dict[str, object] = {}
        if linkage_id is not None:
            metadata_overrides["linkage_id"] = linkage_id
            metadata_overrides["linkage_order_names"] = tuple(
                sorted(component - {name})
            )
            if component_ids and component_ids != [linkage_id]:
                metadata_overrides["legacy_linkage_ids"] = tuple(component_ids)
        result.append(
            legacy_dict_to_order_plan(
                plan,
                current_price=getattr(order, "current_price", None),
                metadata_overrides=metadata_overrides,
            )
        )
    return result


def legacy_dict_to_order_plan(
    plan: dict[str, object],
    *,
    current_price: float | None = None,
    metadata_overrides: Mapping[str, object] | None = None,
) -> OrderPlan:
    pair_name = str(plan["pair"])
    pair = currency_pair(pair_name)
    direction = Direction(int(plan["direction"]))
    order_type = OrderType(str(plan["type"]))
    target_price = float(plan["target_price"])
    take_profit_price = float(plan["tp_price"])
    stop_loss_price = float(plan["lc_price"])
    metadata = {
        key: value
        for key, value in plan.items()
        if key
        not in {
            "for_api_json",
            "candle_analysis_class",
            "linkage_order_classes",
        }
    }
    metadata["order_permission"] = _legacy_bool(
        plan.get("order_permission"),
        default=True,
    )
    if metadata_overrides:
        metadata.update(metadata_overrides)
    intent = OrderIntent(
        pair=pair_name,
        direction=direction,
        order_type=order_type,
        target=target_price,
        target_is_price=True,
        take_profit=take_profit_price,
        take_profit_is_price=True,
        stop_loss=stop_loss_price,
        stop_loss_is_price=True,
        units=int(plan["units"]),
        name=str(plan["name"]),
        priority=int(plan["priority"]),
        order_timeout_min=int(plan["order_timeout_min"]),
        trade_timeout_min=int(plan["trade_timeout_min"]),
        lc_change=tuple(plan.get("lc_change", ())),
        metadata=metadata,
    )
    context_price = current_price
    if context_price is None or float(context_price) == 0:
        context_price = plan.get(
            "current_price",
            plan.get("decision_price", target_price),
        )
    context = OrderContext(
        current_price=float(context_price),
        decision_time=str(plan["decision_time"]),
        move_average=float(plan.get("move_ave", 0)),
        account_mode=int(plan.get("oa_mode", 2)),
    )
    broker_request = BrokerOrderRequest(
        instrument=pair_name,
        units=int(plan["units"]) * direction.value,
        order_type=order_type,
        price=target_price,
        take_profit_price=take_profit_price,
        stop_loss_price=stop_loss_price,
        client_reference=submission_fingerprint(
            pair=pair_name,
            name=str(plan["name"]),
            decision_time=str(plan["decision_time"]),
            direction=direction.value,
            order_type=order_type,
            target_price=target_price,
            units=int(plan["units"]),
        ),
    )
    return OrderPlan(
        intent=intent,
        context=context,
        target_price=pair.round_price(target_price),
        take_profit_price=pair.round_price(take_profit_price),
        stop_loss_price=pair.round_price(stop_loss_price),
        take_profit_range=float(plan["tp_range"]),
        stop_loss_range=float(plan["lc_range"]),
        broker_request=broker_request,
    )


def order_plan_to_legacy_dict(order_plan: OrderPlan) -> dict[str, object]:
    intent = order_plan.intent
    context = order_plan.context
    request = order_plan.broker_request
    pair = currency_pair(intent.pair)
    payload = {
        "order": {
            "instrument": request.instrument,
            "units": str(request.units),
            "type": request.order_type.value,
            "positionFill": "DEFAULT",
            "price": pair.price_to_str(request.price),
            "takeProfitOnFill": {"timeInForce": "GTC", "price": pair.price_to_str(request.take_profit_price)},
            "stopLossOnFill": {"timeInForce": "GTC", "price": pair.price_to_str(request.stop_loss_price)},
        }
    }
    result = {
        "decision_time": context.decision_time,
        "units": intent.units,
        "pair": intent.pair,
        "direction": intent.direction.value,
        "target_price": order_plan.target_price,
        "lc_price": order_plan.stop_loss_price,
        "lc_range": order_plan.stop_loss_range,
        "tp_price": order_plan.take_profit_price,
        "tp_range": order_plan.take_profit_range,
        "type": intent.order_type.value,
        "name": intent.name,
        "name_ymdhms": str(intent.metadata.get("name_ymdhms", intent.name)),
        "oa_mode": context.account_mode,
        "order_timeout_min": intent.order_timeout_min,
        "trade_timeout_min": intent.trade_timeout_min,
        "order_permission": bool(intent.metadata.get("order_permission", True)),
        "priority": intent.priority,
        "watching_price": intent.metadata.get("watching_price", 0),
        "lc_price_original": order_plan.stop_loss_price,
        "tp_price_original": order_plan.take_profit_price,
        "for_api_json": payload,
        "lc_change": list(intent.lc_change),
        "move_ave": context.move_average,
        "candle_lc_change_type": intent.metadata.get("candle_lc_change_type", "5M"),
        "memo": intent.metadata.get("memo", ""),
    }
    result.update(intent.metadata.get("legacy_plan_metadata", {}))
    for key in (
        "linkage_id",
        "linkage_order_names",
        "legacy_linkage_ids",
    ):
        if key in intent.metadata:
            result[key] = intent.metadata[key]
    return result
