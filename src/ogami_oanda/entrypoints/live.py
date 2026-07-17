from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime
from typing import Mapping

import requests

from ogami_oanda.adapters.notifications.discord import DiscordNotifier
from ogami_oanda.adapters.oanda.client import OandaClient
from ogami_oanda.adapters.oanda.execution import OandaExecutionAdapter
from ogami_oanda.adapters.oanda.market_data import OandaMarketDataAdapter
from ogami_oanda.adapters.oanda.query import OandaQueryAdapter
from ogami_oanda.adapters.repositories.csv_trade_history import (
    CsvTradeHistoryRepository,
)
from ogami_oanda.application.services.market_analysis_service import (
    CandidateBuilder,
    MarketAnalysisResult,
    MarketAnalysisService,
)
from ogami_oanda.application.services.order_planner import OrderPlanner
from ogami_oanda.application.services.position_portfolio_service import (
    PositionPortfolioService,
    RegistrationResult,
)
from ogami_oanda.application.services.position_service import PositionService
from ogami_oanda.domain.orders.models import OrderContext
from ogami_oanda.infrastructure.config.loader import load_settings
from ogami_oanda.infrastructure.config.models import AppSettings


class SystemClock:
    def now(self) -> datetime:
        return datetime.now().replace(microsecond=0)


def _no_candidates(context: Mapping[str, object], current_price: float) -> list[dict]:
    return []


@dataclass(frozen=True)
class LiveRunResult:
    analysis: MarketAnalysisResult
    registration: RegistrationResult


class LiveApplication:
    def __init__(self, pair: str, market_data, analysis: MarketAnalysisService, planner: OrderPlanner, portfolio: PositionPortfolioService, clock) -> None:
        self.pair = pair
        self.market_data = market_data
        self.analysis = analysis
        self.planner = planner
        self.portfolio = portfolio
        self.clock = clock

    def run_once(self, *, dry_run: bool = False, decision_time: str | None = None) -> LiveRunResult:
        decision_time = decision_time or self.clock.now().isoformat()
        analysis = self.analysis.analyze(self.pair, decision_time)
        context = OrderContext(current_price=self.market_data.current_price(self.pair), decision_time=decision_time)
        plans = [self.planner.plan(intent, context) for intent in analysis.intents]
        registration = self.portfolio.register_plans(plans, submit=not dry_run)
        return LiveRunResult(analysis, registration)


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
    cancel_pending_on_start: bool = False,
) -> LiveApplication:
    clock = clock or SystemClock()
    pair = pair or settings.trading.default_pair
    if market_data is None or broker_execution is None or broker_query is None:
        client = OandaClient(settings.account(account_name))
        market_data = market_data or OandaMarketDataAdapter(client)
        broker_execution = broker_execution or OandaExecutionAdapter(client)
        broker_query = broker_query or OandaQueryAdapter(client)
    notifier = notifier or DiscordNotifier(settings.notifications, clock, requests.Session())
    history = history or CsvTradeHistoryRepository(settings.paths.history_file)
    position_service = PositionService(broker_execution, broker_query, notifier, history, clock)
    portfolio = PositionPortfolioService(pair, position_service, broker_query, broker_execution, settings.trading)
    portfolio.restore_open_positions()
    portfolio.cancel_pending_on_start(cancel_pending_on_start)
    analysis = MarketAnalysisService(market_data, candidate_builder or _no_candidates, units=int(settings.trading.line_units))
    return LiveApplication(pair, market_data, analysis, OrderPlanner(), portfolio, clock)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run one ogami-oanda live analysis cycle")
    parser.add_argument("--settings", required=True)
    parser.add_argument("--account", default="primary")
    parser.add_argument("--pair")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--cancel-pending-on-start", action="store_true")
    arguments = parser.parse_args(argv)
    application = build_live_application(
        load_settings(arguments.settings),
        account_name=arguments.account,
        pair=arguments.pair,
        cancel_pending_on_start=arguments.cancel_pending_on_start,
    )
    result = application.run_once(dry_run=arguments.dry_run)
    print(f"accepted={len(result.registration.accepted)} rejected={len(result.registration.rejected)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
