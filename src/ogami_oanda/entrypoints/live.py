from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime

from ogami_oanda.adapters.notifications.discord import DiscordNotifier, create_http_session
from ogami_oanda.adapters.oanda.client import OandaClient
from ogami_oanda.adapters.oanda.execution import OandaExecutionAdapter
from ogami_oanda.adapters.oanda.market_data import OandaMarketDataAdapter
from ogami_oanda.adapters.oanda.query import OandaQueryAdapter
from ogami_oanda.adapters.repositories.csv_trade_history import CsvTradeHistoryRepository
from ogami_oanda.application.ports.market_data import MarketDataPort, MarketQuote
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
from ogami_oanda.application.services.position_service import (
    CandleStopLossInput,
    PositionService,
)
from ogami_oanda.domain.market.currency_pair import currency_pair
from ogami_oanda.domain.orders.models import OrderContext, OrderPlan
from ogami_oanda.infrastructure.config.loader import load_settings
from ogami_oanda.infrastructure.config.models import AppSettings
from ogami_oanda.infrastructure.runtime import PollingLoop, Sleeper, SystemClock
from ogami_oanda.strategy.line import LineCandidateBuilder
from ogami_oanda.strategy.position_management import (
    EntryConfirmationPolicy,
    ExitPolicy,
    HedgePolicy,
    LinkagePolicy,
    StopLossPolicy,
)


@dataclass(frozen=True)
class LiveRunResult:
    analysis: MarketAnalysisResult | None
    registration: RegistrationResult
    summary: PortfolioSummary | None = None
    quote: MarketQuote | None = None
    skipped: tuple[str, ...] = ()
    plans: tuple[OrderPlan, ...] = ()


class LiveApplication:
    def __init__(
        self,
        pair: str,
        market_data: MarketDataPort,
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
        self._candle_stop_loss: CandleStopLossInput | None = None

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
        pair = currency_pair(self.pair)
        if pair.round_price(quote.spread) > pair.pips_to_price(pair.spread_limit_pips):
            update_only = True
        first_execution = self._last_analysis_at is None
        elapsed = (now - self._last_analysis_at).total_seconds() if not first_execution else float("inf")
        # The historical runner always performed its initial analysis after the
        # quote, even when that first tick fell in an update-only/spread window.
        should_analyze = first_execution or (
            not update_only
            and self.schedule.should_run_analysis(now, elapsed, update_only=False)
        )
        should_sync_after = (
            not first_execution
            and not update_only
            and self.schedule.should_run_position_update(now)
        )
        should_sync_before = (
            not first_execution
            and (update_only or should_analyze)
        )

        summary = (
            self._sync_positions(quote.mid, dry_run)
            if should_sync_before
            else None
        )
        if not should_analyze:
            if should_sync_after and not should_sync_before:
                summary = self._sync_positions(quote.mid, dry_run)
            reasons = []
            if update_only:
                reasons.append("update_only")
            if not should_sync_before and not should_sync_after:
                reasons.append("outside_sync_window")
            return LiveRunResult(None, RegistrationResult((), ()), summary, quote, tuple(reasons))

        decision_time = decision_time or now.isoformat()
        analysis = self._analyze(decision_time, quote.mid)
        self._candle_stop_loss = self._candle_input(analysis)
        # MarketAnalysisService derives its decision time from the newest M5
        # candle and carries the move average used by legacy reporting.
        context = analysis.order_context or OrderContext(
            current_price=quote.mid,
            decision_time=decision_time,
        )
        plans = tuple(self.planner.plan(intent, context) for intent in analysis.intents)
        registration = self.portfolio.register_plans(list(plans), submit=not dry_run)
        self._last_analysis_at = now
        if should_sync_after:
            summary = self._sync_positions(quote.mid, dry_run)
        return LiveRunResult(analysis, registration, summary, quote, plans=plans)

    def run_forever(
        self,
        *,
        dry_run: bool = False,
        sleeper: Sleeper | None = None,
        max_ticks: int | None = None,
    ) -> tuple[LiveRunResult, ...]:
        """Run legacy-compatible one-second ticks; finite ticks make this testable."""
        loop = PollingLoop[LiveRunResult](
            interval_seconds=1,
            **({"sleeper": sleeper} if sleeper is not None else {}),
        )
        return loop.run(lambda: self.run_once(dry_run=dry_run), max_ticks=max_ticks)

    def _quote(self) -> MarketQuote:
        return self.market_data.current_quote(self.pair)

    def _analyze(self, decision_time: str, current_price: float) -> MarketAnalysisResult:
        return self.analysis.analyze(self.pair, decision_time, current_price=current_price)

    def _sync_positions(
        self,
        current_price: float,
        dry_run: bool,
    ) -> PortfolioSummary:
        if self._candle_stop_loss is None:
            return self.portfolio.sync_all(
                current_price=current_price,
                dry_run=dry_run,
            )
        return self.portfolio.sync_all(
            current_price=current_price,
            candle_stop_loss=self._candle_stop_loss,
            dry_run=dry_run,
        )

    @staticmethod
    def _candle_input(
        analysis: MarketAnalysisResult,
    ) -> CandleStopLossInput | None:
        frame = analysis.frames.get("M5")
        peaks = analysis.peaks.get("M5")
        peak_items = getattr(peaks, "peaks_original", ())
        if frame is None or len(frame) < 2 or not peak_items:
            return None
        return CandleStopLossInput(
            latest_peak=dict(peak_items[0]),
            previous_candle=frame.iloc[1].to_dict(),
        )


class _OfflineSmokeMarketData:
    def __init__(self, pair: str) -> None:
        self.pair = pair
        self.mid = 150.0 if pair.endswith("_JPY") else 1.0

    def current_quote(self, pair: str) -> MarketQuote:
        if pair != self.pair:
            raise ValueError(f"offline smoke configured for {self.pair}, got {pair}")
        return MarketQuote(pair, self.mid, self.mid, self.mid)


class _OfflineSmokeAnalysis:
    def analyze(
        self,
        pair: str,
        decision_time: str,
        *,
        current_price: float | None = None,
    ) -> MarketAnalysisResult:
        return MarketAnalysisResult(
            (),
            {},
            {},
            OrderContext(
                current_price=float(current_price or 0),
                decision_time=decision_time,
            ),
        )


class _OfflineSmokePortfolio:
    def sync_all(self, **_kwargs) -> PortfolioSummary:
        return PortfolioSummary(0, 0, 0, 0)

    def register_plans(
        self,
        _plans: list[OrderPlan],
        submit: bool = True,
    ) -> RegistrationResult:
        del submit
        return RegistrationResult((), ())


def build_offline_smoke_application(
    pair: str = "USD_JPY",
    *,
    clock=None,
) -> LiveApplication:
    """Build a no-network, no-persistence CLI packaging smoke composition."""
    market_data = _OfflineSmokeMarketData(pair)
    return LiveApplication(
        pair,
        market_data,
        _OfflineSmokeAnalysis(),
        OrderPlanner(),
        _OfflineSmokePortfolio(),
        clock or SystemClock(),
    )


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
    account = settings.account(account_name)
    capabilities = broker_query.account_capabilities()
    if capabilities.account_id != account.account_id:
        raise ValueError("Broker account identity does not match configuration")
    if account.require_hedging and not capabilities.hedging_enabled:
        raise ValueError(
            "Configured account must have hedging enabled for positionFill=DEFAULT"
        )
    notifier = notifier or DiscordNotifier(settings.notifications, clock, create_http_session())
    history = history or CsvTradeHistoryRepository(settings.paths.history_file)
    position_service = PositionService(
        broker_execution,
        broker_query,
        notifier,
        history,
        clock,
        entry_confirmation=EntryConfirmationPolicy(),
        stop_loss=StopLossPolicy(),
        exit_policy_factory=ExitPolicy,
    )
    portfolio = PositionPortfolioService(
        pair,
        position_service,
        broker_query,
        broker_execution,
        settings.trading,
        linkage_policy=LinkagePolicy(currency_pair(pair).round_keta),
        hedge_policy=HedgePolicy(),
    )
    portfolio.restore_open_positions()
    if cancel_pending_on_start and not dry_run:
        portfolio.cancel_pending_on_start(True)
    analysis = MarketAnalysisService(
        market_data,
        candidate_builder or LineCandidateBuilder(pair, risk_yen=settings.trading.risk_yen),
        candidate_context_builder=build_line_candidate_context,
        units=int(settings.trading.line_units),
    )
    return LiveApplication(pair, market_data, analysis, OrderPlanner(), portfolio, clock, schedule)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run ogami-oanda live scheduling")
    parser.add_argument("--config", "--settings", dest="config")
    parser.add_argument("--account", default="primary")
    parser.add_argument("--pair")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--cancel-pending-on-start", action="store_true")
    parser.add_argument("--once", action="store_true", help="run one deterministic scheduling tick")
    parser.add_argument(
        "--offline-smoke",
        action="store_true",
        help="run one dependency-free packaging smoke tick (requires --dry-run --once)",
    )
    arguments = parser.parse_args(argv)
    if arguments.offline_smoke:
        if not arguments.dry_run or not arguments.once:
            parser.error("--offline-smoke requires --dry-run and --once")
        application = build_offline_smoke_application(
            arguments.pair or "USD_JPY",
        )
    else:
        if not arguments.config:
            parser.error("--config is required unless --offline-smoke is used")
        application = build_live_application(
            load_settings(arguments.config),
            account_name=arguments.account,
            pair=arguments.pair,
            cancel_pending_on_start=arguments.cancel_pending_on_start,
            dry_run=arguments.dry_run,
        )
    if arguments.once:
        result = application.run_once(dry_run=arguments.dry_run)
        accepted_names = ",".join(result.registration.accepted) or "-"
        rejected_reasons = ",".join(
            f"{name}:{reason}" for name, reason in result.registration.rejected
        ) or "-"
        plans = ",".join(plan.intent.name for plan in result.plans) or "-"
        skipped = ",".join(result.skipped) or "-"
        print(
            f"accepted={len(result.registration.accepted)} "
            f"rejected={len(result.registration.rejected)} skipped={skipped} "
            f"plans={plans} accepted_names={accepted_names} "
            f"rejected_reasons={rejected_reasons}"
        )
    else:
        application.run_forever(dry_run=arguments.dry_run)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
