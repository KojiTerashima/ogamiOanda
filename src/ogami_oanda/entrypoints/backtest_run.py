"""Credential-free composition of the shared trading applications for replay."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Callable, Iterable

from ogami_oanda.adapters.backtest.broker import SimulatedBroker
from ogami_oanda.adapters.backtest.history import SimulationHistory, SimulationNotifier
from ogami_oanda.adapters.backtest.report import BacktestReport
from ogami_oanda.application.services.historical_market import HistoricalMarket, ReplayClock
from ogami_oanda.application.services.order_planner import OrderPlanner
from ogami_oanda.application.services.position_portfolio_service import PositionPortfolioService, PortfolioStartupState
from ogami_oanda.application.services.position_service import PositionService
from ogami_oanda.domain.market.history import HistoricalCandle, utc_time
from ogami_oanda.entrypoints.live import StrategyLiveApplication
from ogami_oanda.strategy.shared.contracts import TradingStrategy, strategy_data_requirements

APPROXIMATIONS = {
    "resolution": "S5", "market_execution": "next_available_S5_open",
    "intrabar_collision": "SL_first; no_intrabar_entry_TP",
    "quote_time": "observed_S5_close_time", "end_positions": "last_bid_ask_close",
    "margin": False, "swap": False, "commission": 0,
}


def release_simulation_history(application, broker, history) -> None:
    """Retain terminal evidence for current slots, not every historical trade."""
    slots = [p for p in application.portfolio.slots if p is not None]
    order_ids = {p.snapshot.order_id for p in slots if p.snapshot.order_id}
    trade_ids = {p.snapshot.trade_id for p in slots if p.snapshot.trade_id}
    broker.release_inactive(order_ids, trade_ids)
    history.seen.intersection_update(trade_ids)
    service = application.portfolio.position_service
    references = order_ids | trade_ids | {p.snapshot.name for p in slots}
    references.update(p.snapshot.client_reference for p in slots if p.snapshot.client_reference)
    references.update(p.runtime.order_plan.broker_request.client_reference for p in slots
                      if p.runtime.order_plan is not None and p.runtime.order_plan.broker_request.client_reference)

    def event_reference(event_id: str) -> str:
        kind, separator, reference = event_id.partition(":")
        if not separator:
            return ""
        if kind == "stop_loss_amended":
            # Amendment IDs append index and price; a name/reference itself
            # may contain colons, so remove exactly the two trailing fields.
            fields = reference.rsplit(":", 2)
            return fields[0] if len(fields) == 3 else ""
        return reference

    service._emitted_event_ids = {event for event in service._emitted_event_ids
                                  if event_reference(event) in references}
    reporter = service.closure_reporting
    reporter._reported_event_ids.intersection_update({f"trade_closed:{trade_id}" for trade_id in trade_ids})
    analytics = reporter.analytics
    for name in ("history_plus_minus", "history_names", "history_name_plus_minus", "result_dic_arr"):
        values = getattr(analytics, name)
        del values[:-7]


def run_backtest(
    strategy: TradingStrategy, strategy_id: str, pair: str, candles: Iterable[HistoricalCandle],
    start: datetime, end: datetime, *, initial_balance: float, output_dir: str | Path,
    slippage_pips: float = 0, metadata: dict | None = None,
    progress: Callable[[datetime], None] | None = None,
) -> dict:
    start, end = utc_time(start), utc_time(end)
    if start >= end or start.microsecond or end.microsecond or start.second % 5 or end.second % 5:
        raise ValueError("backtest range must increase and align to S5")
    requirements = strategy_data_requirements(strategy)
    market = HistoricalMarket(pair, requirements)
    clock = ReplayClock(start)
    history = SimulationHistory()
    # Validate broker settings before creating output files.
    broker = SimulatedBroker(pair, clock, initial_balance=initial_balance, slippage_pips=slippage_pips)
    report = BacktestReport(output_dir, {**(metadata or {}), "strategy_id": strategy_id,
                            "pair": pair, "from": start.isoformat(), "to": end.isoformat(),
                            "requirements": requirements, "initial_balance": initial_balance,
                            "slippage_pips": slippage_pips, "approximations": APPROXIMATIONS}, initial_balance)
    broker.event_sink = report.event
    market.gap_sink = report.gap
    service = PositionService(broker, broker, SimulationNotifier(), history, clock)
    portfolio = PositionPortfolioService(pair, service, broker, broker, strategy_id=strategy_id)
    broker.operation_reason = lambda reference: next(
        (mutation.reason for mutation in reversed(portfolio.pending_mutations)
         if mutation.broker_reference_id == reference), "")
    application = StrategyLiveApplication(pair, strategy, strategy_id, market, OrderPlanner(), portfolio, clock)
    count = 0
    warmup = 0
    skipped: dict[str, int] = {}
    progress_day = None
    previous = None
    try:
        for candle in candles:
            if previous is not None and candle.time <= previous:
                raise ValueError("historical candles must be in strictly increasing order")
            previous = candle.time
            if candle.time >= end:
                break
            if candle.time < start:
                market.advance(candle)
                warmup += 1
                continue
            if count == 0 and requirements and not market.ready:
                raise ValueError("insufficient warmup candles for strategy requirements")
            if market.last is None and candle.time > start:
                market.record_gap(start, candle.time)
            broker.advance(candle)
            market.advance(candle)
            clock.set(candle.end)
            count += 1
            if candle.end < end:
                result = application.run_once(now=clock.now(), dry_run=False)
                if portfolio.startup_state is PortfolioStartupState.QUARANTINED or portfolio.pending_mutations:
                    raise RuntimeError("simulation portfolio could not reconcile broker state")
                for reason in result.skipped:
                    skipped[reason] = skipped.get(reason, 0) + 1
                for event in result.runtime_events:
                    report.event({"event_id": f"runtime:{event.event_id}", "time": event.occurred_at.isoformat(),
                                  "event": event.kind, "pair": pair, "name": event.name,
                                  "reason": event.data.get("reason", "")})
            report.mark(candle.end, broker.balance, broker.unrealized_pl)
            if count % 256 == 0:
                release_simulation_history(application, broker, history)
            if progress is not None and candle.time.date() != progress_day:
                progress_day = candle.time.date()
                progress(candle.end)
        if not count:
            raise ValueError("no S5 data in evaluation interval")
        if broker.last.end < end:
            market.record_gap(broker.last.end, end)
        # A watching entry has no broker order to finalize. Cancel it locally
        # before the final sync can turn the last quote into a fresh submission.
        for index, position in enumerate(portfolio.slots):
            if position is not None and position.snapshot.waiting_order:
                cancelled = position.cancelled().with_runtime(submission_reason="END_OF_TEST")
                portfolio.slots[index] = cancelled
                service._events_once(service._event(
                    "order_cancelled", cancelled, cancelled.snapshot, reason="END_OF_TEST",
                ), False)
        broker.finalize()
        # The terminal broker refuses new submissions and market advancement.
        # This sync only consumes final cancellation and liquidation evidence.
        portfolio.sync_all(current_price=market.current_price(pair))
        if (
            portfolio.startup_state is not PortfolioStartupState.READY
            or portfolio.pending_mutations
            or any(position is not None and (position.snapshot.life or position.snapshot.waiting_order)
                   for position in portfolio.slots)
            or broker.pending_orders()
            or broker.open_positions()
        ):
            raise RuntimeError("simulation terminal state is not fully reconciled")
        for event in application.runtime_events.drain():
            report.event({"event_id": f"runtime:{event.event_id}", "time": event.occurred_at.isoformat(),
                          "event": event.kind, "pair": pair, "name": event.name,
                          "reason": event.data.get("reason", "")})
        report.mark(broker.last.end, broker.balance, broker.unrealized_pl)
        summary = {
            "pair": pair, "currency": pair.split("_")[1], "trade_count": broker.completed_trades,
            "win_rate": broker.winning_trades / broker.completed_trades if broker.completed_trades else None,
            "profit_factor": broker.gross_profit / broker.gross_loss if broker.gross_loss else None,
            "gross_profit": broker.gross_profit, "gross_loss": broker.gross_loss,
            "realized_pl": broker.balance - broker.initial_balance, "pips": broker.total_pips,
            "initial_balance": broker.initial_balance, "ending_balance": broker.balance,
            "ending_unrealized_pl": broker.unrealized_pl, "ending_equity": broker.balance + broker.unrealized_pl,
            "max_drawdown": report.max_drawdown, "max_drawdown_pct": report.max_drawdown_pct,
            "monthly_realized_pl": dict(sorted(broker.monthly.items())), "evaluated_candles": count,
            "warmup_candles": warmup, "gap_count": market.gap_count, "gap_seconds": market.gap_seconds,
            "skipped": skipped,
        }
        report.finish(summary, metadata={"final_strategy_state": strategy.dump_state()})
        return summary
    except BaseException as error:
        report.fail(error)
        raise
