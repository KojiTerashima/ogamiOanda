from __future__ import annotations

import argparse
import inspect
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from functools import wraps
from pathlib import Path
from typing import Callable, Protocol

from ogami_oanda.adapters.notifications.discord import (
    DiscordNotifier,
    create_http_session,
)
from ogami_oanda.adapters.legacy.main_analysis.backend import MainSourceAnalysis
from ogami_oanda.adapters.legacy.main_analysis.source import DEFAULT_SOURCE_DIRECTORY
from ogami_oanda.entrypoints.main_analysis import bind_main_analysis
from ogami_oanda.adapters.oanda.client import OandaClient
from ogami_oanda.adapters.oanda.execution import OandaExecutionAdapter
from ogami_oanda.adapters.oanda.market_data import OandaMarketDataAdapter
from ogami_oanda.adapters.oanda.query import OandaQueryAdapter
from ogami_oanda.adapters.repositories.csv_trade_history import (
    CsvTradeHistoryRepository,
)
from ogami_oanda.adapters.repositories.json_position_state import (
    JsonPositionStateRepository,
)
from ogami_oanda.application.errors import (
    ExternalServiceAuthorizationError,
    TransientExternalServiceError,
)
from ogami_oanda.application.ports.market_data import MarketDataPort, MarketQuote
from ogami_oanda.application.ports.position_state import (
    PositionStateRepository,
    account_identity_hash,
    validated_strategy_state,
)
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
from ogami_oanda.application.services.runtime_event_buffer import RuntimeEventBuffer
from ogami_oanda.domain.market.currency_pair import currency_pair
from ogami_oanda.domain.orders.models import OrderContext, OrderPlan
from ogami_oanda.domain.positions.models import PositionEvent, TradeState
from ogami_oanda.infrastructure.config.loader import load_settings
from ogami_oanda.infrastructure.config.models import AppSettings
from ogami_oanda.infrastructure.logging.daily_file import setup_daily_file_logging
from ogami_oanda.infrastructure.runtime import PollingLoop, Sleeper, SystemClock
from ogami_oanda.strategy.shared.contracts import (
    StrategyDecision,
    StrategyInput,
    StrategyQuote,
    TradingStrategy,
    strategy_data_requirements,
)
from ogami_oanda.strategy.original.line import LineCandidateBuilder
from ogami_oanda.strategy.shared.loader import StrategyPluginError, load_strategy
from ogami_oanda.strategy.shared.position_management import (
    EntryConfirmationPolicy,
    ExitPolicy,
    HedgePolicy,
    LinkagePolicy,
    StopLossPolicy,
)


@dataclass(frozen=True)
class LiveFailure:
    service: str
    message: str
    retry_after_seconds: float | None = None
    category: str = "availability"
    status_code: int | None = None
    operation: str | None = None


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
    runtime_events: tuple[PositionEvent, ...] = ()
    failure: LiveFailure | None = None


class LiveRunObserver(Protocol):
    def on_result(self, result: LiveRunResult) -> None: ...

    def on_error(self, error: BaseException) -> None: ...


def _notify_observer_result(
    observer: LiveRunObserver | None,
    result: LiveRunResult,
) -> None:
    if observer is None:
        return
    callback = (
        getattr(observer, "on_result", None)
        or getattr(observer, "on_tick", None)
        or getattr(observer, "report", None)
        or (observer if callable(observer) else None)
    )
    if callback is not None:
        callback(result)


def _notify_observer_error(
    observer: LiveRunObserver | None,
    error: BaseException,
) -> None:
    if observer is None:
        return
    callback = getattr(observer, "on_error", None)
    if callback is not None:
        callback(error)


def _run_forever_with_observer(
    application: object,
    *,
    dry_run: bool,
    observer: LiveRunObserver,
) -> object:
    run_forever = getattr(application, "run_forever")
    try:
        parameters = inspect.signature(run_forever).parameters
    except (TypeError, ValueError):
        # C-extension callables and a few test doubles do not expose a
        # signature. Production applications accept the observer, so prefer
        # passing it when introspection cannot decide.
        return run_forever(dry_run=dry_run, observer=observer)
    kwargs: dict[str, object] = {"dry_run": dry_run}
    if "observer" in parameters or any(
        parameter.kind is inspect.Parameter.VAR_KEYWORD
        for parameter in parameters.values()
    ):
        kwargs["observer"] = observer
    return run_forever(**kwargs)


def _configured_log_dir(settings: AppSettings) -> str | None:
    paths = getattr(settings, "paths", None)
    if paths is None:
        return None
    log_dir = getattr(paths, "log_dir", None)
    return str(log_dir) if log_dir else None


def _collect_runtime_events(method):
    """Attach and clear the current tick's transient events on a result."""

    @wraps(method)
    def wrapped(self, *args, **kwargs):
        result = method(self, *args, **kwargs)
        return replace(result, runtime_events=self.runtime_events.drain())

    return wrapped


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
        runtime_events: RuntimeEventBuffer | None = None,
        authorization_recovery: Callable[[], PortfolioStartupState] | None = None,
    ) -> None:
        self.pair = pair
        self.market_data = market_data
        self.analysis = analysis
        self.planner = planner
        self.portfolio = portfolio
        self.clock = clock
        self.schedule = schedule or TradingSchedule()
        self._startup = startup or (lambda: None)
        self.runtime_events = runtime_events or RuntimeEventBuffer()
        self._authorization_recovery = authorization_recovery
        position_service = getattr(self.portfolio, "position_service", None)
        set_event_sink = getattr(position_service, "set_event_sink", None)
        if set_event_sink is not None:
            set_event_sink(self.runtime_events.publish)
        self._last_analysis_at: datetime | None = None
        self._candle_stop_loss: CandleStopLossInput | None = None
        self._broker_retry_not_before: datetime | None = None
        self._broker_backoff_seconds = 1.0
        self._broker_backoff_cap_seconds = 60.0

        self._authorization_blocked = False

    @_collect_runtime_events
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
        if (
            summary is not None
            and getattr(
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
        # The analysis carries its decision boundary and the move average
        # used by existing order planning and reporting.
        context = analysis.order_context or OrderContext(
            current_price=quote.mid,
            decision_time=decision_time,
        )
        plans = tuple(self.planner.plan(intent, context) for intent in analysis.intents)
        registration = self._register_plans(plans, dry_run)
        self._last_analysis_at = now
        if should_sync_after:
            summary = self._sync_positions(quote.mid, dry_run)
        return LiveRunResult(
            analysis, registration, summary, quote, plans=plans,
            strategy_decision=getattr(self.analysis, "last_decision", None),
        )

    def _register_plans(self, plans: tuple[OrderPlan, ...], dry_run: bool) -> RegistrationResult:
        return self.portfolio.register_plans(list(plans), submit=not dry_run)

    def run_forever(
        self,
        *,
        dry_run: bool = False,
        sleeper: Sleeper | None = None,
        max_ticks: int | None = None,
        observer: LiveRunObserver | None = None,
    ) -> tuple[LiveRunResult, ...]:
        """Run legacy-compatible one-second ticks; finite ticks make this testable."""
        loop = PollingLoop[LiveRunResult](
            interval_seconds=1,
            **({"sleeper": sleeper} if sleeper is not None else {}),
        )
        def tick() -> LiveRunResult:
            try:
                result = self.run_resilient_once(dry_run=dry_run)
            except BaseException as error:
                _notify_observer_error(observer, error)
                raise
            _notify_observer_result(observer, result)
            return result

        return loop.run(tick, max_ticks=max_ticks)

    def run_resilient_once(self, *, dry_run: bool = False) -> LiveRunResult:
        now = self.clock.now()
        if (
            self._broker_retry_not_before is not None
            and now < self._broker_retry_not_before
        ):
            return self._empty_result("broker_backoff")

        if self._authorization_blocked:
            try:
                recovery_state = self._recover_authorization()
            except ExternalServiceAuthorizationError as error:
                return self._authorization_failure_result(error, now)
            except TransientExternalServiceError as error:
                return self._transient_failure_result(error, now)
            self._authorization_blocked = False
            self._reset_broker_backoff()
            if recovery_state is PortfolioStartupState.READY:
                return self._empty_result("broker_authorization_recovered")
            if recovery_state is PortfolioStartupState.RECONCILING:
                return self._empty_result("broker_reconciliation")
            if recovery_state is PortfolioStartupState.QUARANTINED:
                return self._empty_result("portfolio_quarantined")
            raise ValueError(
                f"Unexpected authorization recovery state: {recovery_state}"
            )

        try:
            result = self.run_once(now=now, dry_run=dry_run)
        except ExternalServiceAuthorizationError as error:
            return self._authorization_failure_result(error, now)
        except TransientExternalServiceError as error:
            return self._transient_failure_result(error, now)
        self._reset_broker_backoff()
        return result

    def _recover_authorization(self) -> PortfolioStartupState:
        if self._authorization_recovery is not None:
            return self._authorization_recovery()
        recovery = self.portfolio.restore_and_reconcile()
        return recovery.state

    def _authorization_failure_result(
        self,
        error: ExternalServiceAuthorizationError,
        now: datetime,
    ) -> LiveRunResult:
        self._authorization_blocked = True
        delay = self._schedule_broker_backoff(now)
        return self._empty_result(
            "broker_authorization",
            failure=LiveFailure(
                error.service,
                str(error),
                retry_after_seconds=delay,
                category="authorization",
                status_code=error.status_code,
                operation=error.operation,
            ),
        )

    def _transient_failure_result(
        self,
        error: TransientExternalServiceError,
        now: datetime,
    ) -> LiveRunResult:
        delay = self._schedule_broker_backoff(
            now,
            requested_delay=error.retry_after_seconds,
        )
        return self._empty_result(
            "broker_unavailable",
            failure=LiveFailure(
                getattr(error, "service", "oanda"),
                str(error),
                retry_after_seconds=delay,
            ),
        )

    def _schedule_broker_backoff(
        self,
        now: datetime,
        *,
        requested_delay: float | None = None,
    ) -> float:
        delay = requested_delay or self._broker_backoff_seconds
        self._broker_retry_not_before = now + timedelta(seconds=delay)
        self._broker_backoff_seconds = min(
            self._broker_backoff_seconds * 2,
            self._broker_backoff_cap_seconds,
        )
        return delay

    def _reset_broker_backoff(self) -> None:
        self._broker_retry_not_before = None
        self._broker_backoff_seconds = 1.0

    def _empty_result(
        self,
        skipped: str,
        *,
        failure: LiveFailure | None = None,
    ) -> LiveRunResult:
        return LiveRunResult(
            None,
            RegistrationResult((), ()),
            skipped=(skipped,),
            runtime_events=self.runtime_events.drain(),
            failure=failure,
        )

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
        frame = getattr(analysis, "completed_frames", {}).get("M5")
        previous_index = 0
        if frame is None:
            frame = analysis.frames.get("M5")
            previous_index = 1
        peaks = analysis.peaks.get("M5")
        peak_items = getattr(peaks, "peaks_original", ())
        if frame is None or len(frame) <= previous_index or not peak_items:
            return None
        return CandleStopLossInput(
            latest_peak=dict(peak_items[0]),
            previous_candle=frame.iloc[previous_index].to_dict(),
        )


class StrategyLiveApplication(LiveApplication):
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
        runtime_events: RuntimeEventBuffer | None = None,
        authorization_recovery: Callable[[], PortfolioStartupState] | None = None,
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
        self.runtime_events = runtime_events or RuntimeEventBuffer()
        self._authorization_recovery = authorization_recovery
        position_service = getattr(self.portfolio, "position_service", None)
        set_event_sink = getattr(position_service, "set_event_sink", None)
        if set_event_sink is not None:
            set_event_sink(self.runtime_events.publish)
        self.data_requirements = strategy_data_requirements(strategy)
        self._original_profile = getattr(strategy, "evaluation_profile", None) == "original"
        self._last_analysis_at = None
        self._candle_stop_loss = None
        self._original_dry_run = False
        if self._original_profile:
            self.analysis = MarketAnalysisService(market_data, strategy=strategy)
        self._strategy_loaded = False
        self._broker_retry_not_before: datetime | None = None
        self._broker_backoff_seconds = 1.0
        self._broker_backoff_cap_seconds = 60.0
        self._authorization_blocked = False

    @_collect_runtime_events
    def run_once(
        self,
        *,
        now: datetime | None = None,
        dry_run: bool = False,
        decision_time: str | None = None,
    ) -> LiveRunResult:
        now = now or self.clock.now()
        if self._original_profile:
            self._original_dry_run = dry_run
            # Use the same scheduler, including its first-tick exception and
            # sync-before / analyze / sync-after ordering.
            return LiveApplication.run_once.__wrapped__(
                self, now=now, dry_run=dry_run, decision_time=decision_time,
            )
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
            summary = self._sync_positions(quote.mid, dry_run)
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

            candle_frames = {
                granularity: self.market_data.candles(self.pair, granularity, count)
                for granularity, count in self.data_requirements.items()
            }
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
                candles=candle_frames.get("M1"),
                candle_frames=candle_frames,
                evaluation_time=now,
            )
            decision = self.strategy.decide(strategy_input)
            if not isinstance(decision, StrategyDecision):
                raise TypeError("strategy decide() must return StrategyDecision")

            protection = decision.candle_protection
            self._candle_stop_loss = (
                CandleStopLossInput(protection.latest_peak, protection.previous_candle)
                if protection is not None else None
            )
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

            context = decision.order_context or OrderContext(
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
        observer: LiveRunObserver | None = None,
    ) -> tuple[LiveRunResult, ...]:
        loop = PollingLoop[LiveRunResult](
            interval_seconds=1,
            **({"sleeper": sleeper} if sleeper is not None else {}),
        )
        def tick() -> LiveRunResult:
            try:
                result = self.run_resilient_once(dry_run=dry_run)
            except BaseException as error:
                _notify_observer_error(observer, error)
                raise
            _notify_observer_result(observer, result)
            return result

        return loop.run(tick, max_ticks=max_ticks)

    def run_resilient_once(self, *, dry_run: bool = False) -> LiveRunResult:
        now = self.clock.now()
        if (
            self._broker_retry_not_before is not None
            and now < self._broker_retry_not_before
        ):
            return self._empty_result("broker_backoff")

        if self._authorization_blocked:
            try:
                recovery_state = self._recover_authorization()
            except ExternalServiceAuthorizationError as error:
                return self._authorization_failure_result(error, now)
            except TransientExternalServiceError as error:
                return self._transient_failure_result(error, now)
            self._authorization_blocked = False
            self._reset_broker_backoff()
            if recovery_state is PortfolioStartupState.READY:
                return self._empty_result("broker_authorization_recovered")
            if recovery_state is PortfolioStartupState.RECONCILING:
                return self._empty_result("broker_reconciliation")
            if recovery_state is PortfolioStartupState.QUARANTINED:
                return self._empty_result("portfolio_quarantined")
            raise ValueError(
                f"Unexpected authorization recovery state: {recovery_state}"
            )

        try:
            result = self.run_once(now=now, dry_run=dry_run)
        except ExternalServiceAuthorizationError as error:
            return self._authorization_failure_result(error, now)
        except TransientExternalServiceError as error:
            return self._transient_failure_result(error, now)
        self._reset_broker_backoff()
        return result

    def _recover_authorization(self) -> PortfolioStartupState:
        if self._authorization_recovery is not None:
            return self._authorization_recovery()
        recovery = self.portfolio.restore_and_reconcile()
        return recovery.state

    def _authorization_failure_result(
        self,
        error: ExternalServiceAuthorizationError,
        now: datetime,
    ) -> LiveRunResult:
        self._authorization_blocked = True
        delay = self._schedule_broker_backoff(now)
        return self._empty_result(
            "broker_authorization",
            failure=LiveFailure(
                error.service,
                str(error),
                retry_after_seconds=delay,
                category="authorization",
                status_code=error.status_code,
                operation=error.operation,
            ),
        )

    def _transient_failure_result(
        self,
        error: TransientExternalServiceError,
        now: datetime,
    ) -> LiveRunResult:
        delay = self._schedule_broker_backoff(
            now,
            requested_delay=error.retry_after_seconds,
        )
        return self._empty_result(
            "broker_unavailable",
            failure=LiveFailure(
                getattr(error, "service", "oanda"),
                str(error),
                retry_after_seconds=delay,
            ),
        )

    def _schedule_broker_backoff(
        self,
        now: datetime,
        *,
        requested_delay: float | None = None,
    ) -> float:
        delay = requested_delay or self._broker_backoff_seconds
        self._broker_retry_not_before = now + timedelta(seconds=delay)
        self._broker_backoff_seconds = min(
            self._broker_backoff_seconds * 2,
            self._broker_backoff_cap_seconds,
        )
        return delay

    def _reset_broker_backoff(self) -> None:
        self._broker_retry_not_before = None
        self._broker_backoff_seconds = 1.0

    def _empty_result(
        self,
        skipped: str,
        *,
        failure: LiveFailure | None = None,
    ) -> LiveRunResult:
        return LiveRunResult(
            None,
            RegistrationResult((), ()),
            skipped=(skipped,),
            runtime_events=self.runtime_events.drain(),
            failure=failure,
        )

    def _load_strategy_state_once(self) -> None:
        if self._strategy_loaded:
            return
        self.strategy.load_state(self.portfolio.strategy_state)
        self._strategy_loaded = True

    def _register_plans(self, plans: tuple[OrderPlan, ...], dry_run: bool) -> RegistrationResult:
        if dry_run:
            return RegistrationResult((), ())
        return super()._register_plans(plans, dry_run)

    def _analyze(self, decision_time: str, current_price: float) -> MarketAnalysisResult:
        self._load_strategy_state_once()
        result = super()._analyze(decision_time, current_price)
        if not self._original_dry_run:
            self.portfolio.set_strategy_checkpoint_state(
                self.strategy.dump_state(), persist=True,
            )
        return result

    def _strategy_positions(self) -> tuple:
        snapshots = []
        for position in getattr(self.portfolio, "slots", ()):
            if position is None or not (
                position.snapshot.life or position.runtime.close_requested
            ):
                continue
            source = position.runtime.source or position.snapshot.source
            snapshot = position.snapshot
            if position.runtime.close_requested and not snapshot.life:
                snapshot = replace(
                    snapshot,
                    life=True,
                    trade_state=TradeState.OPEN,
                )
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
    main_analysis_dir: str | Path = DEFAULT_SOURCE_DIRECTORY,
) -> LiveApplication:
    analysis_backend = MainSourceAnalysis(source_directory=main_analysis_dir) if candidate_builder is None else None
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

    def verify_account(*, force: bool = False) -> None:
        nonlocal account_verified
        if account_verified and not force:
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
    startup_authorization_error: ExternalServiceAuthorizationError | None = None
    try:
        verify_account()
    except ExternalServiceAuthorizationError as error:
        startup_authorization_error = error
        startup_deferred = True
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
    runtime_events = RuntimeEventBuffer()
    position_service = PositionService(
        broker_execution,
        broker_query,
        notifier,
        history,
        clock,
        entry_confirmation=EntryConfirmationPolicy(),
        stop_loss=StopLossPolicy(),
        exit_policy_factory=ExitPolicy,
        event_sink=runtime_events.publish,
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

    def reconcile_portfolio() -> PortfolioStartupState:
        nonlocal startup_complete
        startup = portfolio.restore_and_reconcile()
        if startup.state is PortfolioStartupState.QUARANTINED:
            notifier.send(
                f"Portfolio startup quarantined: {startup.reason}",
                pair=pair,
            )
        if (
            not startup_complete
            and startup.state is PortfolioStartupState.READY
            and cancel_pending_on_start
            and not dry_run
        ):
            portfolio.cancel_pending_on_start(True)
        startup_complete = True
        return startup.state

    def start() -> None:
        nonlocal startup_authorization_error
        if startup_complete:
            return
        if startup_authorization_error is not None:
            error = startup_authorization_error
            startup_authorization_error = None
            raise error
        verify_account()
        reconcile_portfolio()

    def recover_authorization() -> PortfolioStartupState:
        verify_account(force=True)
        return reconcile_portfolio()

    if not startup_deferred:
        try:
            start()
        except ExternalServiceAuthorizationError as error:
            startup_authorization_error = error
        except TransientExternalServiceError:
            pass
    analysis = MarketAnalysisService(
        market_data,
        candidate_builder or LineCandidateBuilder(pair, risk_yen=settings.trading.risk_yen),
        candidate_context_builder=build_line_candidate_context,
        units=int(settings.trading.line_units),
        analysis_backend=analysis_backend,
        analysis_mode="live",
        risk_yen=settings.trading.risk_yen,
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
        runtime_events=runtime_events,
        authorization_recovery=recover_authorization,
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
    main_analysis_dir: str | Path = DEFAULT_SOURCE_DIRECTORY,
) -> StrategyLiveApplication:
    """Compose a live runner for an already validated trusted strategy."""

    bind_main_analysis(strategy, mode="live", main_analysis_dir=main_analysis_dir)

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

    def verify_account(*, force: bool = False) -> None:
        nonlocal account_verified
        if account_verified and not force:
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
    startup_authorization_error: ExternalServiceAuthorizationError | None = None
    try:
        verify_account()
    except ExternalServiceAuthorizationError as error:
        startup_authorization_error = error
        startup_deferred = True
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
    runtime_events = RuntimeEventBuffer()
    position_service = PositionService(
        broker_execution,
        broker_query,
        notifier,
        history,
        clock,
        entry_confirmation=EntryConfirmationPolicy(),
        stop_loss=StopLossPolicy(),
        exit_policy_factory=ExitPolicy,
        event_sink=runtime_events.publish,
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

    def reconcile_portfolio() -> PortfolioStartupState:
        nonlocal startup_complete
        startup = portfolio.restore_and_reconcile()
        if startup.state is PortfolioStartupState.QUARANTINED:
            notifier.send(
                f"Portfolio startup quarantined: {startup.reason}",
                pair=pair,
            )
        if (
            not startup_complete
            and startup.state is PortfolioStartupState.READY
            and cancel_pending_on_start
            and not dry_run
        ):
            portfolio.cancel_pending_on_start(True)
        startup_complete = True
        return startup.state

    def start() -> None:
        nonlocal startup_authorization_error
        if startup_complete:
            return
        if startup_authorization_error is not None:
            error = startup_authorization_error
            startup_authorization_error = None
            raise error
        verify_account()
        reconcile_portfolio()

    def recover_authorization() -> PortfolioStartupState:
        verify_account(force=True)
        return reconcile_portfolio()

    if not startup_deferred:
        try:
            start()
        except ExternalServiceAuthorizationError as error:
            startup_authorization_error = error
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
        runtime_events=runtime_events,
        authorization_recovery=recover_authorization,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run ogami-oanda live scheduling")
    parser.add_argument("--config", "--settings", dest="config")
    parser.add_argument("--account", default="primary")
    parser.add_argument("--pair")
    parser.add_argument("--main-analysis-dir", default=DEFAULT_SOURCE_DIRECTORY, metavar="PATH",
                        help="main source directory for original (default: ../main, relative to working directory)")
    parser.add_argument(
        "--strategy", choices=("original", "matcha"),
        help="packaged strategy to run (default: original; shared is not runnable)",
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--cancel-pending-on-start", action="store_true")
    parser.add_argument("--once", action="store_true", help="run one deterministic scheduling tick")
    parser.add_argument(
        "--trace-candidates",
        action="store_true",
        help="print built-in line candidate counts and rejection reasons",
    )
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
    if arguments.strategy and (arguments.strategy_py is not None or arguments.strategy_yaml is not None):
        parser.error("--strategy cannot be combined with --strategy-py or --strategy-yaml")
    if arguments.strategy == "matcha":
        strategy_dir = Path(__file__).resolve().parents[1] / "strategy" / "matcha"
        arguments.strategy_py = strategy_dir / "strategy.py"
        arguments.strategy_yaml = strategy_dir / "parameters.yaml"
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
        log_dir = _configured_log_dir(settings)
        if log_dir is not None:
            setup_daily_file_logging(log_dir)
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
                main_analysis_dir=arguments.main_analysis_dir,
            )
        else:
            application = build_live_application(
                settings,
                account_name=arguments.account,
                pair=arguments.pair,
                cancel_pending_on_start=arguments.cancel_pending_on_start,
                dry_run=arguments.dry_run,
                main_analysis_dir=arguments.main_analysis_dir,
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
        diagnostics = getattr(result.analysis, "candidate_diagnostics", None)
        if arguments.trace_candidates and diagnostics is not None:
            from ogami_oanda.entrypoints.live_console import (
                format_candidate_diagnostics,
            )

            print("candidates " + format_candidate_diagnostics(diagnostics))
    else:
        from ogami_oanda.entrypoints.live_console import ConsoleLiveReporter

        reporter = ConsoleLiveReporter(
            application,
            dry_run=arguments.dry_run,
            trace_candidates=arguments.trace_candidates,
        )
        _run_forever_with_observer(
            application,
            dry_run=arguments.dry_run,
            observer=reporter,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
