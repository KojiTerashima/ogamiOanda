from __future__ import annotations

from dataclasses import dataclass, field

from ogami_oanda.application.ports.notifications import Notifier
from ogami_oanda.application.ports.trade_history import TradeHistoryRepository
from ogami_oanda.domain.market.currency_pair import currency_pair
from ogami_oanda.domain.positions.managed_position import ManagedPosition
from ogami_oanda.domain.positions.models import PositionEvent, PositionSnapshot

LEGACY_HISTORY_COLUMNS = (
    "name",
    "pair",
    "res",
    "pl_per_units",
    "units",
    "max_plus",
    "max_minus",
    "order_time",
    "target_price",
    "take_time",
    "take_price",
    "end_time",
    "end_price",
    "lc_price",
    "lc_price_original_plan",
    "lc_range",
    "tp_price",
    "tp_range",
    "lc_change",
    "orderID",
    "tradeID",
    "name_only",
    "plus_minus",
    "position_keep_time",
    "name_ymdhms",
    "tp_price_original_plan",
    "move_ave5",
    "move_ave60",
    "memo",
    "current_price_gap",
    "rr",
    "target_price_range",
)


@dataclass
class PortfolioAnalytics:
    total_yen: float = 0.0
    total_yen_max: float = 0.0
    total_yen_min: float = 0.0
    total_pips: float = 0.0
    total_pips_max: float = 0.0
    total_pips_min: float = 0.0
    plus_yen_position_num: int = 0
    minus_yen_position_num: int = 0
    before_latest_price_diff: float = 0.0
    before_latest_pl_pips: float = 0.0
    before_latest_name: str = ""
    history_plus_minus: list[float] = field(default_factory=list)
    history_names: list[str] = field(default_factory=list)
    history_name_plus_minus: list[dict[str, object]] = field(default_factory=list)

    def apply(self, record: dict[str, object], price_diff: float) -> None:
        realized = float(record["res"])
        pips = float(record["pl_per_units"])
        self.total_yen = round(self.total_yen + realized, 2)
        self.total_yen_max = max(self.total_yen_max, self.total_yen)
        self.total_yen_min = min(self.total_yen_min, self.total_yen)
        self.total_pips = round(self.total_pips + pips, 2)
        self.total_pips_max = max(self.total_pips_max, self.total_pips)
        self.total_pips_min = min(self.total_pips_min, self.total_pips)
        if realized < 0:
            self.minus_yen_position_num += 1
        else:
            self.plus_yen_position_num += 1
        self.before_latest_price_diff = price_diff
        self.before_latest_pl_pips = pips
        self.before_latest_name = str(record["name"])
        self.history_plus_minus.append(pips)
        self.history_names.append(str(record["name"]))
        self.history_name_plus_minus.append({
            "name": record["name_only"],
            "price_diff": price_diff,
            "pl_pips": pips,
        })


class ClosureReportingService:
    def __init__(
        self,
        history: TradeHistoryRepository,
        notifier: Notifier,
        analytics: PortfolioAnalytics | None = None,
    ) -> None:
        self.history = history
        self.notifier = notifier
        self.analytics = analytics or PortfolioAnalytics()
        self._reported_event_ids: set[str] = set()

    def report(self, event: PositionEvent) -> dict[str, object] | None:
        if event.kind != "trade_closed" or event.event_id in self._reported_event_ids:
            return None
        position = event.data.get("position")
        broker_snapshot = event.data.get("broker_snapshot")
        if not isinstance(position, ManagedPosition) or not isinstance(broker_snapshot, PositionSnapshot):
            return None
        if position.runtime.order_plan is None:
            return None
        record, price_diff = self._legacy_record(position, broker_snapshot, event)
        self.history.append(record)
        self.analytics.apply(record, price_diff)
        self.notifier.send(
            f"Trade closed: {event.name} {record['pl_per_units']}p {record['res']}",
            category="close",
            pair=event.pair,
        )
        self._reported_event_ids.add(event.event_id)
        return record

    @staticmethod
    def _legacy_record(
        position: ManagedPosition,
        broker_snapshot: PositionSnapshot,
        event: PositionEvent,
    ) -> tuple[dict[str, object], float]:
        plan = position.runtime.order_plan
        assert plan is not None
        pair = currency_pair(event.pair)
        direction = position.runtime.direction
        close_price = float(broker_snapshot.average_close_price or broker_snapshot.current_price or position.runtime.target_price)
        price_diff = pair.round_price((close_price - position.runtime.target_price) * direction)
        pl_pips = pair.price_to_pips(price_diff)
        intent = plan.intent
        metadata = intent.metadata
        lc_range_pips = pair.price_to_pips(plan.stop_loss_range)
        tp_range_pips = pair.price_to_pips(plan.take_profit_range)
        rr = round(tp_range_pips / lc_range_pips, 2) if lc_range_pips else 0
        lc_change = metadata.get("lc_change_str", "")
        if not lc_change and intent.lc_change:
            lc_change = ",".join(f"({item.get('trigger')}-{item.get('ensure')})" for item in intent.lc_change)
        values = {
            "name": event.name,
            "pair": event.pair,
            "res": str(broker_snapshot.realized_pl),
            "pl_per_units": pl_pips,
            "units": str(intent.units * direction),
            "max_plus": position.runtime.max_unrealized_pl,
            "max_minus": position.runtime.min_unrealized_pl,
            "order_time": position.runtime.registered_at,
            "target_price": position.runtime.target_price,
            "take_time": broker_snapshot.open_time or position.runtime.filled_at,
            "take_price": str(broker_snapshot.target_price or position.runtime.target_price),
            "end_time": event.occurred_at,
            "end_price": str(close_price),
            "lc_price": position.runtime.current_stop_loss,
            "lc_price_original_plan": plan.stop_loss_price,
            "lc_range": lc_range_pips,
            "tp_price": plan.take_profit_price,
            "tp_range": tp_range_pips,
            "lc_change": lc_change,
            "orderID": str(broker_snapshot.order_id or position.snapshot.order_id or ""),
            "tradeID": str(broker_snapshot.trade_id or position.snapshot.trade_id or ""),
            "name_only": event.name[:-5],
            "plus_minus": 1 if broker_snapshot.realized_pl > 0 else -1,
            "position_keep_time": str(broker_snapshot.elapsed_seconds),
            "name_ymdhms": metadata.get("name_ymdhms", event.name),
            "tp_price_original_plan": plan.take_profit_price,
            "move_ave5": pair.price_to_pips(plan.context.move_average),
            "move_ave60": pair.price_to_pips(float(metadata.get("move_ave60", 0))),
            "memo": metadata.get("memo", ""),
            "current_price_gap": float(metadata.get("current_price_gap", 0)),
            "rr": rr,
            "target_price_range": float(metadata.get("target_distance_pips", 0)),
        }
        return {column: values[column] for column in LEGACY_HISTORY_COLUMNS}, price_diff
