from __future__ import annotations

from ogami_oanda.application.ports.notifications import Notifier
from ogami_oanda.application.ports.trade_history import TradeHistoryRepository
from ogami_oanda.application.services.portfolio_analytics import (
    PortfolioAnalytics,
    publish_portfolio_analytics,
)
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
        if analytics is None:
            self._restore_from_history()

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
        if not self.history.append_once(record, unique_field="tradeID"):
            self._reported_event_ids.add(event.event_id)
            return None
        self.analytics.apply(
            record,
            price_diff,
            lc_change_count=self._lc_change_count(position),
        )
        publish_portfolio_analytics(event.pair, self.analytics)
        self.notifier.send(
            f"Trade closed: {event.name} {record['pl_per_units']}p {record['res']}",
            category="close",
            pair=event.pair,
        )
        self._reported_event_ids.add(event.event_id)
        return record

    def _restore_from_history(self) -> None:
        published_pairs: set[str] = set()
        for raw_record in self.history.read_all():
            record = dict(raw_record)
            trade_id = str(record.get("tradeID", ""))
            pair_name = str(record.get("pair", ""))
            if not trade_id or not pair_name:
                continue
            try:
                pips = float(record["pl_per_units"])
                price_diff = currency_pair(pair_name).pips_to_price(pips)
                lc_change_count = str(record.get("lc_change", "")).count("(")
                self.analytics.apply(
                    record,
                    price_diff,
                    lc_change_count=lc_change_count,
                )
            except (KeyError, TypeError, ValueError):
                continue
            self._reported_event_ids.add(f"trade_closed:{trade_id}")
            published_pairs.add(pair_name)
        for pair_name in published_pairs:
            publish_portfolio_analytics(pair_name, self.analytics)

    @staticmethod
    def _lc_change_count(position: ManagedPosition) -> int:
        runtime = position.runtime
        return int(runtime.applied_lc_change_index >= 0) + int(
            runtime.candle_stop_loss_done
        )

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
            lc_change = "".join(
                f",({pair.price_to_pips(float(item.get('trigger', 0)))}p-"
                f"{pair.price_to_pips(float(item.get('ensure', 0)))}p)"
                for item in intent.lc_change[:2]
            )
        max_plus, max_minus = ClosureReportingService._excursion_pips(
            position,
            broker_snapshot,
        )
        values = {
            "name": event.name,
            "pair": event.pair,
            "res": str(broker_snapshot.realized_pl),
            "pl_per_units": pl_pips,
            "units": str(float(intent.units * direction)),
            "max_plus": max_plus,
            "max_minus": max_minus,
            "order_time": position.runtime.registered_at,
            "target_price": position.runtime.target_price,
            "take_time": broker_snapshot.open_time or position.runtime.filled_at,
            "take_price": str(
                float(
                    broker_snapshot.target_price
                    or position.runtime.target_price
                )
            ),
            "end_time": event.occurred_at,
            "end_price": str(close_price),
            "lc_price": position.runtime.current_stop_loss,
            "lc_price_original_plan": metadata.get(
                "lc_price_original",
                metadata.get(
                    "lc_price_original_plan",
                    plan.stop_loss_price,
                ),
            ),
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
            "tp_price_original_plan": metadata.get(
                "tp_price_original",
                metadata.get(
                    "tp_price_original_plan",
                    plan.take_profit_price,
                ),
            ),
            "move_ave5": pair.price_to_pips(plan.context.move_average),
            "move_ave60": pair.price_to_pips(float(metadata.get("move_ave60", 0))),
            "memo": metadata.get("memo", ""),
            "current_price_gap": pair.price_to_pips(
                float(
                    metadata.get(
                        "current_price_gap",
                        metadata.get("current_candle_price_gap", 0),
                    )
                )
            ),
            "rr": round(rr, 1),
            "target_price_range": float(
                metadata.get(
                    "target_distance_pips",
                    metadata.get("gap_target_price_pips", 0),
                )
            ),
        }
        return {column: values[column] for column in LEGACY_HISTORY_COLUMNS}, price_diff

    @staticmethod
    def _excursion_pips(
        position: ManagedPosition,
        broker_snapshot: PositionSnapshot,
    ) -> tuple[float, float]:
        """Project the best available runtime excursion into legacy pips.

        A migrated legacy plan may carry the already-observed pips explicitly.
        Otherwise JPY-quoted trades can be reconstructed from account-yen P/L
        and units.  For other account/quote combinations, the last observed
        market price is the only lossless excursion value in the snapshot.
        """

        plan = position.runtime.order_plan
        assert plan is not None
        metadata = plan.intent.metadata
        explicit_plus = metadata.get("max_plus_pips", metadata.get("max_plus"))
        explicit_minus = metadata.get("max_minus_pips", metadata.get("max_minus"))
        if explicit_plus is not None or explicit_minus is not None:
            return (
                float(explicit_plus or 0),
                float(explicit_minus or 0),
            )

        pair = currency_pair(position.snapshot.pair)
        observed_pips = 0.0
        observed_price = position.snapshot.current_price
        if observed_price is not None:
            observed_pips = pair.price_to_pips(
                (
                    float(observed_price)
                    - position.runtime.target_price
                )
                * position.runtime.direction
            )
        observed_plus = max(0.0, observed_pips)
        observed_minus = min(0.0, observed_pips)
        units = abs(int(broker_snapshot.units or plan.intent.units))
        if units and position.snapshot.pair.endswith("_JPY"):
            observed_plus = max(
                observed_plus,
                pair.price_to_pips(position.runtime.max_unrealized_pl / units),
            )
            observed_minus = min(
                observed_minus,
                pair.price_to_pips(position.runtime.min_unrealized_pl / units),
            )
        return observed_plus, observed_minus
