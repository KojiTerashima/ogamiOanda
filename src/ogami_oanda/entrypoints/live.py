from __future__ import annotations

import argparse
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Mapping, Protocol

from ogami_oanda.adapters.notifications.discord import DiscordNotifier, create_http_session
from ogami_oanda.adapters.oanda.client import OandaClient
from ogami_oanda.adapters.oanda.execution import OandaExecutionAdapter
from ogami_oanda.adapters.oanda.market_data import OandaMarketDataAdapter
from ogami_oanda.adapters.oanda.query import OandaQueryAdapter
from ogami_oanda.adapters.repositories.csv_trade_history import CsvTradeHistoryRepository
from ogami_oanda.application.ports.market_data import MarketQuote
from ogami_oanda.application.scheduling import TradingSchedule
from ogami_oanda.application.services.line_candidate_context_builder import (
    build_line_candidate_context,
)
from ogami_oanda.application.services.market_analysis_service import (
    CandidateBuilder,
    MarketAnalysisResult,
    MarketAnalysisService,
)
from ogami_oanda.application.services.order_planner import OrderPlanner
from ogami_oanda.application.services.position_portfolio_service import (
    PortfolioSummary,
    PositionPortfolioService,
    RegistrationResult,
)
from ogami_oanda.application.services.position_service import PositionService
from ogami_oanda.domain.market.currency_pair import currency_pair
from ogami_oanda.domain.orders.models import OrderContext
from ogami_oanda.infrastructure.config.loader import load_settings
from ogami_oanda.infrastructure.config.models import AppSettings
from ogami_oanda.strategy.line import LineCandidateBuilder


class SystemClock:
    def now(self) -> datetime:
        return datetime.now().replace(microsecond=0)


class Sleeper(Protocol):
    def __call__(self, seconds: float) -> None: ...


def _no_candidates(context: Mapping[str, object], current_price: float) -> list[dict]:
    """Explicit test-only composition; production uses ``LineCandidateBuilder``."""
    return []


@dataclass(frozen=True)
class LiveRunResult:
    analysis: MarketAnalysisResult | None
    registration: RegistrationResult
    summary: PortfolioSummary | None = None
    quote: MarketQuote | None = None
    skipped: tuple[str, ...] = ()


class LiveApplication:
    def __init__(
        self,
        pair: str,
        market_data,
        analysis: MarketAnalysisService,
        planner: OrderPlanner,
        portfolio: PositionPortfolioService,
        clock,
        schedule: TradingSchedule | None = None,
    ) -> None:
        self.pair = pair
        self.market_data = market_data
        self.analysis = analysis
        self.planner = planner
        self.portfolio = portfolio
        self.clock = clock
        self.schedule = schedule or TradingSchedule()
        self._last_analysis_at: datetime | None = None

    def run_once(
        self,
        *,
        now: datetime | None = None,
        dry_run: bool = False,
        decision_time: str | None = None,
    ) -> LiveRunResult:
        now = now or self.clock.now()
        if self.schedule.is_market_closed(now):
            return LiveRunResult(None, RegistrationResult((), ()), skipped=("market_closed",))

        quote = self._quote()
        update_only = self.schedule.is_update_only_window(now)
        if currency_pair(self.pair).price_to_pips(quote.spread) > currency_pair(self.pair).spread_limit_pips:
            update_only = True
        elapsed = (now - self._last_analysis_at).total_seconds() if self._last_analysis_at else float("inf")
        should_analyze = not update_only and (
            self._last_analysis_at is None
            or self.schedule.should_run_analysis(now, elapsed, update_only=False)
        )
        should_sync = update_only or self.schedule.should_run_position_update(now)

        summary = self.portfolio.sync_all(current_price=quote.mid, dry_run=dry_run) if should_sync else None
        if not should_analyze:
            reasons = []
            if update_only:
                reasons.append("update_only")
            if not should_sync:
                reasons.append("outside_sync_window")
            return LiveRunResult(None, RegistrationResult((), ()), summary, quote, tuple(reasons))

        decision_time = decision_time or now.isoformat()
        analysis = self._analyze(decision_time, quote.mid)
        context = OrderContext(current_price=quote.mid, decision_time=decision_time)
        plans = [self.planner.plan(intent, context) for intent in analysis.intents]
        registration = self.portfolio.register_plans(plans, submit=not dry_run)
        self._last_analysis_at = now
        return LiveRunResult(analysis, registration, summary, quote)

    def run_forever(
        self,
        *,
        dry_run: bool = False,
        sleeper: Sleeper = time.sleep,
        max_ticks: int | None = None,
    ) -> tuple[LiveRunResult, ...]:
        """Run legacy-compatible one-second ticks; finite ticks make this testable."""
        results: list[LiveRunResult] = []
        tick = 0
        while max_ticks is None or tick < max_ticks:
            results.append(self.run_once(dry_run=dry_run))
            tick += 1
            if max_ticks is None or tick < max_ticks:
                sleeper(1)
        return tuple(results)

    def _quote(self) -> MarketQuote:
        quote_method = getattr(self.market_data, "current_quote", None)
        if quote_method is not None:
            return quote_method(self.pair)
        details_method = getattr(self.market_data, "current_price_details", None)
        if details_method is not None:
            details = details_method(self.pair)
            return MarketQuote(self.pair, details["bid"], details["ask"], details["mid"])
        mid = self.market_data.current_price(self.pair)
        return MarketQuote(self.pair, mid, mid, mid)

    def _analyze(self, decision_time: str, current_price: float) -> MarketAnalysisResult:
        try:
            return self.analysis.analyze(self.pair, decision_time, current_price=current_price)
        except TypeError as error:
            # Lightweight injected test analyses used the original two-argument protocol.
            if "current_price" not in str(error):
                raise
            return self.analysis.analyze(self.pair, decision_time)


def build_live_application(
    settings: AppSettings,
    account_name: str = "primary",
    pair: str | None = None,
    candidate_builder: CandidateBuilder | None = None,
    *,
    market_data=None,
    broker_execution=None,
    broker_query=None,
    notifier=None,
    history=None,
    clock=None,
    schedule: TradingSchedule | None = None,
    cancel_pending_on_start: bool = False,
    dry_run: bool = False,
) -> LiveApplication:
    clock = clock or SystemClock()
    pair = pair or settings.trading.default_pair
    if market_data is None or broker_execution is None or broker_query is None:
        # One account-level client is deliberately shared across all OANDA ports.
        client = OandaClient(settings.account(account_name))
        market_data = market_data or OandaMarketDataAdapter(client)
        broker_execution = broker_execution or OandaExecutionAdapter(client)
        broker_query = broker_query or OandaQueryAdapter(client)
    notifier = notifier or DiscordNotifier(settings.notifications, clock, create_http_session())
    history = history or CsvTradeHistoryRepository(settings.paths.history_file)
    position_service = PositionService(broker_execution, broker_query, notifier, history, clock)
    portfolio = PositionPortfolioService(pair, position_service, broker_query, broker_execution, settings.trading)
    portfolio.restore_open_positions()
    if cancel_pending_on_start and not dry_run:
        portfolio.cancel_pending_on_start(True)
    analysis = MarketAnalysisService(
        market_data,
        candidate_builder or LineCandidateBuilder(pair),
        candidate_context_builder=build_line_candidate_context,
        units=int(settings.trading.line_units),
    )
    return LiveApplication(pair, market_data, analysis, OrderPlanner(), portfolio, clock, schedule)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run ogami-oanda live scheduling")
    parser.add_argument("--config", "--settings", dest="config", required=True)
    parser.add_argument("--account", default="primary")
    parser.add_argument("--pair")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--cancel-pending-on-start", action="store_true")
    parser.add_argument("--once", action="store_true", help="run one deterministic scheduling tick")
    arguments = parser.parse_args(argv)
    application = build_live_application(
        load_settings(arguments.config),
        account_name=arguments.account,
        pair=arguments.pair,
        cancel_pending_on_start=arguments.cancel_pending_on_start,
        dry_run=arguments.dry_run,
    )
    if arguments.once:
        result = application.run_once(dry_run=arguments.dry_run)
        print(f"accepted={len(result.registration.accepted)} rejected={len(result.registration.rejected)} skipped={','.join(result.skipped)}")
    else:
        application.run_forever(dry_run=arguments.dry_run)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
