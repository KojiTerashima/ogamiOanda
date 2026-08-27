from __future__ import annotations

import argparse
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable

from ogami_oanda.adapters.notifications.discord import DiscordNotifier, create_http_session
from ogami_oanda.adapters.oanda.client import OandaClient
from ogami_oanda.adapters.oanda.execution import OandaExecutionAdapter
from ogami_oanda.adapters.oanda.market_data import OandaMarketDataAdapter
from ogami_oanda.adapters.oanda.query import OandaQueryAdapter
from ogami_oanda.adapters.repositories.csv_trade_history import CsvTradeHistoryRepository
from ogami_oanda.adapters.repositories.json_position_state import (
    JsonPositionStateRepository,
)
from ogami_oanda.application.ports.market_data import MarketDataPort, MarketQuote
from ogami_oanda.application.ports.position_state import (
    PositionStateRepository,
    account_identity_hash,
    validated_strategy_state,
)
from ogami_oanda.application.errors import TransientExternalServiceError
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
    PortfolioStartupState,
    PortfolioSummary,
    PositionPortfolioService,
    RegistrationResult,
    StrategyCommandResult,
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
from ogami_oanda.strategy.contracts import (
    StrategyDecision,
    StrategyInput,
    StrategyQuote,
    TradingStrategy,
)
from ogami_oanda.strategy.loader import StrategyPluginError, load_strategy
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
    strategy_decision: StrategyDecision | None = None
    strategy_command_result: StrategyCommandResult | None = None


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
        startup: Callable[[], None] | None = None,
    ) -> None:
        self.pair = pair
        self.market_data = market_data
        self.analysis = analysis
        self.planner = planner
        self.portfolio = portfolio
        self.clock = clock
        self.schedule = schedule or TradingSchedule()
        self._startup = startup or (lambda: None)
        self._last_analysis_at: datetime | None = None
        self._candle_stop_loss: CandleStopLossInput | None = None
        self._broker_retry_not_before: datetime | None = None
        self._broker_backoff_seconds = 1.0
        self._broker_backoff_cap_seconds = 60.0

    def run_once(
        self,
        *,
        now: datetime | None = None,
        dry_run: bool = False,
        decision_time: str | None = None,
    ) -> LiveRunResult:
        now = now or self.clock.now()
        self._startup()
        if (
            getattr(
                self.portfolio,
                "startup_state",
                PortfolioStartupState.READY,
            )
            is PortfolioStartupState.QUARANTINED
        ):
            return LiveRunResult(
                None,
                RegistrationResult((), ()),
                skipped=("portfolio_quarantined",),
            )
        reconcile = getattr(self.portfolio, "reconcile_pending_mutations", None)
        if reconcile is not None and not reconcile():
            return LiveRunResult(
                None,
                RegistrationResult((), ()),
                skipped=("broker_reconciliation",),
            )
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
        return loop.run(
            lambda: self.run_resilient_once(dry_run=dry_run),
            max_ticks=max_ticks,
        )

    def run_resilient_once(self, *, dry_run: bool = False) -> LiveRunResult:
        now = self.clock.now()
        if (
            self._broker_retry_not_before is not None
            and now < self._broker_retry_not_before
        ):
            return LiveRunResult(
                None,
                RegistrationResult((), ()),
                skipped=("broker_backoff",),
            )
        try:
            result = self.run_once(now=now, dry_run=dry_run)
        except TransientExternalServiceError as error:
            delay = error.retry_after_seconds or self._broker_backoff_seconds
            self._broker_retry_not_before = now + timedelta(seconds=delay)
            self._broker_backoff_seconds = min(
                self._broker_backoff_seconds * 2,
                self._broker_backoff_cap_seconds,
            )
            return LiveRunResult(
                None,
                RegistrationResult((), ()),
                skipped=("broker_unavailable",),
            )
        self._broker_retry_not_before = None
        self._broker_backoff_seconds = 1.0
        return result

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


class StrategyLiveApplication:
    """Evaluate one trusted strategy plugin on every open-market tick."""

    def __init__(
        self,
        pair: str,
        strategy: TradingStrategy,
        strategy_id: str,
        market_data: MarketDataPort,
        planner: OrderPlanner,
        portfolio: PositionPortfolioService,
        clock,
        schedule: TradingSchedule | None = None,
        startup: Callable[[], None] | None = None,
        *,
        max_quote_age: timedelta | None = None,
    ) -> None:
        if not strategy_id:
            raise ValueError("strategy_id must not be empty")
        if max_quote_age is not None and max_quote_age.total_seconds() <= 0:
            raise ValueError("max_quote_age must be positive")
        self.pair = pair
        self.strategy = strategy
        self.strategy_id = strategy_id
        self.market_data = market_data
        self.planner = planner
        self.portfolio = portfolio
        self.clock = clock
        self.schedule = schedule or TradingSchedule()
        self.max_quote_age = max_quote_age
        self._startup = startup or (lambda: None)
        self._strategy_loaded = False
        self._broker_retry_not_before: datetime | None = None
        self._broker_backoff_seconds = 1.0
        self._broker_backoff_cap_seconds = 60.0

    def run_once(
        self,
        *,
        now: datetime | None = None,
        dry_run: bool = False,
        decision_time: str | None = None,
    ) -> LiveRunResult:
        now = now or self.clock.now()
        self._startup()
        if (
            getattr(
                self.portfolio,
                "startup_state",
                PortfolioStartupState.READY,
            )
            is PortfolioStartupState.QUARANTINED
        ):
            return self._skipped("portfolio_quarantined")
        reconcile = getattr(self.portfolio, "reconcile_pending_mutations", None)
        if reconcile is not None and not reconcile():
            return self._skipped("broker_reconciliation")
        if self.schedule.is_market_closed(now):
            return self._skipped("market_closed")

        self._load_strategy_state_once()
        pre_tick_state = (
            validated_strategy_state(self.strategy.dump_state())
            if dry_run
            else None
        )
        try:
            quote = self.market_data.current_quote(self.pair)
            skipped = self._entry_safety_reasons(quote, now)
            summary = self.portfolio.sync_all(
                current_price=quote.mid,
                dry_run=dry_run,
            )
            if (
                getattr(
                    self.portfolio,
                    "startup_state",
                    PortfolioStartupState.READY,
                )
                is PortfolioStartupState.QUARANTINED
            ):
                return LiveRunResult(
                    None,
                    RegistrationResult((), ()),
                    summary,
                    quote,
                    ("portfolio_quarantined",),
                )
            if getattr(self.portfolio, "pending_mutations", ()):
                return LiveRunResult(
                    None,
                    RegistrationResult((), ()),
                    summary,
                    quote,
                    ("broker_reconciliation",),
                )

            candles = self.market_data.candles(self.pair, "M1", 1000)
            strategy_input = StrategyInput(
                quote=StrategyQuote(
                    pair=quote.pair,
                    bid=quote.bid,
                    ask=quote.ask,
                    mid=quote.mid,
                    tradeable=quote.tradeable,
                    source_time=quote.source_time,
                ),
                positions=self._strategy_positions(),
                candles=candles,
                evaluation_time=now,
            )
            decision = self.strategy.decide(strategy_input)
            if not isinstance(decision, StrategyDecision):
                raise TypeError("strategy decide() must return StrategyDecision")

            if not dry_run:
                self.portfolio.set_strategy_checkpoint_state(
                    self.strategy.dump_state(),
                    persist=True,
                )
            command_result = self.portfolio.execute_strategy_commands(
                decision.commands,
                dry_run=dry_run,
            )
            if not command_result.allows_intents:
                reason = (
                    "broker_reconciliation"
                    if command_result.unresolved
                    else "strategy_command_rejected"
                )
                return LiveRunResult(
                    None,
                    RegistrationResult((), ()),
                    summary,
                    quote,
                    (reason,),
                    strategy_decision=decision,
                    strategy_command_result=command_result,
                )

            if skipped:
                return LiveRunResult(
                    None,
                    RegistrationResult((), ()),
                    summary,
                    quote,
                    skipped,
                    strategy_decision=decision,
                    strategy_command_result=command_result,
                )

            context = OrderContext(
                current_price=quote.mid,
                decision_time=decision_time or now.isoformat(),
            )
            plans = tuple(
                self.planner.plan(intent, context)
                for intent in decision.intents
            )
            registration = (
                RegistrationResult((), ())
                if dry_run or not plans
                else self.portfolio.register_plans(list(plans), submit=True)
            )
            return LiveRunResult(
                None,
                registration,
                summary,
                quote,
                plans=plans,
                strategy_decision=decision,
                strategy_command_result=command_result,
            )
        finally:
            if dry_run and pre_tick_state is not None:
                self.strategy.load_state(pre_tick_state)

    def run_forever(
        self,
        *,
        dry_run: bool = False,
        sleeper: Sleeper | None = None,
        max_ticks: int | None = None,
    ) -> tuple[LiveRunResult, ...]:
        loop = PollingLoop[LiveRunResult](
            interval_seconds=1,
            **({"sleeper": sleeper} if sleeper is not None else {}),
        )
        return loop.run(
            lambda: self.run_resilient_once(dry_run=dry_run),
            max_ticks=max_ticks,
        )

    def run_resilient_once(self, *, dry_run: bool = False) -> LiveRunResult:
        now = self.clock.now()
        if (
            self._broker_retry_not_before is not None
            and now < self._broker_retry_not_before
        ):
            return self._skipped("broker_backoff")
        try:
            result = self.run_once(now=now, dry_run=dry_run)
        except TransientExternalServiceError as error:
            delay = error.retry_after_seconds or self._broker_backoff_seconds
            self._broker_retry_not_before = now + timedelta(seconds=delay)
            self._broker_backoff_seconds = min(
                self._broker_backoff_seconds * 2,
                self._broker_backoff_cap_seconds,
            )
            return self._skipped("broker_unavailable")
        self._broker_retry_not_before = None
        self._broker_backoff_seconds = 1.0
        return result

    def _load_strategy_state_once(self) -> None:
        if self._strategy_loaded:
            return
        self.strategy.load_state(self.portfolio.strategy_state)
        self._strategy_loaded = True

    def _strategy_positions(self) -> tuple:
        snapshots = []
        for position in getattr(self.portfolio, "slots", ()):
            if position is None or not position.snapshot.life:
                continue
            source = position.runtime.source or position.snapshot.source
            snapshot = position.snapshot
            if source != snapshot.source:
                snapshot = replace(snapshot, source=source)
            snapshots.append(snapshot)
        return tuple(snapshots)

    def _entry_safety_reasons(
        self,
        quote: MarketQuote,
        now: datetime,
    ) -> tuple[str, ...]:
        reasons = []
        if self.schedule.is_update_only_window(now):
            reasons.append("update_only")
        pair = currency_pair(self.pair)
        if pair.round_price(quote.spread) > pair.pips_to_price(
            pair.spread_limit_pips
        ):
            reasons.append("wide_spread")
        if quote.pair != self.pair:
            reasons.append("quote_pair_mismatch")
        if quote.tradeable is not True:
            reasons.append("quote_untradeable")
        if not self._quote_is_fresh(quote, now):
            reasons.append("stale_quote")
        return tuple(reasons)

    def _quote_is_fresh(self, quote: MarketQuote, now: datetime) -> bool:
        source_time = quote.source_time
        if source_time is None:
            return False
        if not isinstance(source_time, datetime):
            return False
        if now.tzinfo is None or source_time.tzinfo is None:
            return False
        age = now - source_time
        if age < timedelta(0):
            return False
        age_limit = self.max_quote_age
        if age_limit is None:
            config = getattr(self.strategy, "config", None)
            configured_ms = getattr(config, "max_latency_ms", None)
            if isinstance(configured_ms, (int, float)) and configured_ms > 0:
                age_limit = timedelta(milliseconds=configured_ms)
        if age_limit is None:
            return True
        return age <= age_limit

    @staticmethod
    def _skipped(reason: str) -> LiveRunResult:
        return LiveRunResult(
            None,
            RegistrationResult((), ()),
            skipped=(reason,),
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
    if clock is None:
        clock = type(
            "_OfflineSmokeClock",
            (),
            {"now": staticmethod(lambda: datetime(2026, 1, 2, 10, 0, 0))},
        )()
    return LiveApplication(
        pair,
        market_data,
        _OfflineSmokeAnalysis(),
        OrderPlanner(),
        _OfflineSmokePortfolio(),
        clock,
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
    state_repository: PositionStateRepository | None = None,
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
    if (
        account.environment == "live"
        and not dry_run
        and not account.live_trading_enabled
    ):
        raise ValueError(
            "Live account requires explicit live trading opt-in"
        )
    if account.environment not in {"practice", "live"}:
        raise ValueError("Account environment must be practice or live")
    if not account.account_id or not account.access_token:
        raise ValueError("Configured account credentials are incomplete")

    account_verified = False

    def verify_account() -> None:
        nonlocal account_verified
        if account_verified:
            return
        capabilities = broker_query.account_capabilities()
        if capabilities.account_id != account.account_id:
            raise ValueError(
                "Broker account identity does not match configuration"
            )
        if account.require_hedging and not capabilities.hedging_enabled:
            raise ValueError(
                "Configured account must have hedging enabled for positionFill=DEFAULT"
            )
        account_verified = True

    startup_deferred = False
    try:
        verify_account()
    except TransientExternalServiceError:
        startup_deferred = True
    notifier = notifier or DiscordNotifier(settings.notifications, clock, create_http_session())
    history = history or CsvTradeHistoryRepository(settings.paths.history_file)
    account_hash = account_identity_hash(account.account_id)
    if state_repository is None and settings.paths.position_state_dir:
        state_repository = JsonPositionStateRepository(
            Path(settings.paths.position_state_dir)
            / f"{account_hash}-{pair}.json"
        )
    if state_repository is None and not dry_run:
        raise ValueError(
            "Non-dry trading requires a position state repository"
        )
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
        state_repository=state_repository,
        account_hash=account_hash,
        state_writable=not dry_run,
    )
    startup_complete = False

    def start() -> None:
        nonlocal startup_complete
        if startup_complete:
            return
        verify_account()
        startup = portfolio.restore_and_reconcile()
        if startup.state is PortfolioStartupState.QUARANTINED:
            notifier.send(
                f"Portfolio startup quarantined: {startup.reason}",
                pair=pair,
            )
        if (
            startup.state is PortfolioStartupState.READY
            and cancel_pending_on_start
            and not dry_run
        ):
            portfolio.cancel_pending_on_start(True)
        startup_complete = True

    if not startup_deferred:
        try:
            start()
        except TransientExternalServiceError:
            pass
    analysis = MarketAnalysisService(
        market_data,
        candidate_builder or LineCandidateBuilder(pair, risk_yen=settings.trading.risk_yen),
        candidate_context_builder=build_line_candidate_context,
        units=int(settings.trading.line_units),
    )
    return LiveApplication(
        pair,
        market_data,
        analysis,
        OrderPlanner(),
        portfolio,
        clock,
        schedule,
        startup=start,
    )


def build_strategy_live_application(
    settings: AppSettings,
    strategy: TradingStrategy,
    strategy_id: str,
    account_name: str = "primary",
    pair: str | None = None,
    *,
    market_data=None,
    broker_execution=None,
    broker_query=None,
    notifier=None,
    history=None,
    state_repository: PositionStateRepository | None = None,
    clock=None,
    schedule: TradingSchedule | None = None,
    cancel_pending_on_start: bool = False,
    dry_run: bool = False,
    max_quote_age: timedelta | None = None,
) -> StrategyLiveApplication:
    """Compose a live runner for an already validated trusted strategy."""

    clock = clock or SystemClock()
    pair = pair or settings.trading.default_pair
    if market_data is None or broker_execution is None or broker_query is None:
        client = OandaClient(settings.account(account_name))
        market_data = market_data or OandaMarketDataAdapter(client)
        broker_execution = broker_execution or OandaExecutionAdapter(client)
        broker_query = broker_query or OandaQueryAdapter(client)
    account = settings.account(account_name)
    if (
        account.environment == "live"
        and not dry_run
        and not account.live_trading_enabled
    ):
        raise ValueError("Live account requires explicit live trading opt-in")
    if account.environment not in {"practice", "live"}:
        raise ValueError("Account environment must be practice or live")
    if not account.account_id or not account.access_token:
        raise ValueError("Configured account credentials are incomplete")

    account_verified = False

    def verify_account() -> None:
        nonlocal account_verified
        if account_verified:
            return
        capabilities = broker_query.account_capabilities()
        if capabilities.account_id != account.account_id:
            raise ValueError(
                "Broker account identity does not match configuration"
            )
        if account.require_hedging and not capabilities.hedging_enabled:
            raise ValueError(
                "Configured account must have hedging enabled for positionFill=DEFAULT"
            )
        account_verified = True

    startup_deferred = False
    try:
        verify_account()
    except TransientExternalServiceError:
        startup_deferred = True
    notifier = notifier or DiscordNotifier(
        settings.notifications,
        clock,
        create_http_session(),
    )
    history = history or CsvTradeHistoryRepository(settings.paths.history_file)
    account_hash = account_identity_hash(account.account_id)
    if state_repository is None and settings.paths.position_state_dir:
        state_repository = JsonPositionStateRepository(
            Path(settings.paths.position_state_dir)
            / f"{account_hash}-{pair}.json"
        )
    if state_repository is None and not dry_run:
        raise ValueError("Non-dry trading requires a position state repository")
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
        state_repository=state_repository,
        account_hash=account_hash,
        state_writable=not dry_run,
        strategy_id=strategy_id,
    )
    startup_complete = False

    def start() -> None:
        nonlocal startup_complete
        if startup_complete:
            return
        verify_account()
        startup = portfolio.restore_and_reconcile()
        if startup.state is PortfolioStartupState.QUARANTINED:
            notifier.send(
                f"Portfolio startup quarantined: {startup.reason}",
                pair=pair,
            )
        if (
            startup.state is PortfolioStartupState.READY
            and cancel_pending_on_start
            and not dry_run
        ):
            portfolio.cancel_pending_on_start(True)
        startup_complete = True

    if not startup_deferred:
        try:
            start()
        except TransientExternalServiceError:
            pass
    return StrategyLiveApplication(
        pair,
        strategy,
        strategy_id,
        market_data,
        OrderPlanner(),
        portfolio,
        clock,
        schedule,
        startup=start,
        max_quote_age=max_quote_age,
    )


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
    parser.add_argument(
        "--strategy-py",
        metavar="PATH",
        help="trusted package-local strategy Python module",
    )
    parser.add_argument(
        "--strategy-yaml",
        metavar="PATH",
        help="trusted package-local strategy YAML configuration",
    )
    arguments = parser.parse_args(argv)
    has_strategy_py = arguments.strategy_py is not None
    has_strategy_yaml = arguments.strategy_yaml is not None
    if has_strategy_py != has_strategy_yaml:
        parser.error("--strategy-py and --strategy-yaml must be supplied together")
    if arguments.offline_smoke:
        if not arguments.dry_run or not arguments.once:
            parser.error("--offline-smoke requires --dry-run and --once")
        if has_strategy_py:
            parser.error("--offline-smoke cannot be combined with strategy options")
        application = build_offline_smoke_application(
            arguments.pair or "USD_JPY",
        )
    else:
        if not arguments.config:
            parser.error("--config is required unless --offline-smoke is used")
        settings = load_settings(arguments.config)
        if has_strategy_py:
            try:
                loaded = load_strategy(arguments.strategy_py, arguments.strategy_yaml)
            except StrategyPluginError as exc:
                parser.error(str(exc))
            application = build_strategy_live_application(
                settings,
                loaded.strategy,
                loaded.strategy_id,
                account_name=arguments.account,
                pair=arguments.pair,
                cancel_pending_on_start=arguments.cancel_pending_on_start,
                dry_run=arguments.dry_run,
            )
        else:
            application = build_live_application(
                settings,
                account_name=arguments.account,
                pair=arguments.pair,
                cancel_pending_on_start=arguments.cancel_pending_on_start,
                dry_run=arguments.dry_run,
            )
    if arguments.once:
        result = application.run_resilient_once(dry_run=arguments.dry_run)
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
