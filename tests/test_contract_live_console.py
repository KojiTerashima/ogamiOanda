from datetime import datetime
from io import StringIO
from types import SimpleNamespace

import pytest

from ogami_oanda.application.services.position_portfolio_service import (
    PortfolioSummary,
    RegistrationResult,
)
from ogami_oanda.application.ports.market_data import MarketQuote
from ogami_oanda.domain.positions.models import PositionEvent
from ogami_oanda.entrypoints.live import LiveRunResult
from ogami_oanda.entrypoints.live_console import (
    ConsoleLiveReporter,
    LiveFailure,
)
from ogami_oanda.strategy.line import CandidateDiagnostics


class _Clock:
    def now(self):
        return datetime(2026, 8, 28, 12, 34, 56)


class _Portfolio:
    def __init__(self, summary):
        self._summary = summary

    def summary(self):
        return self._summary


def _result(*, failure=None, events=(), skipped=()):
    return LiveRunResult(
        analysis=None,
        registration=RegistrationResult((), ()),
        summary=PortfolioSummary(
            watching=0,
            pending=1,
            open=1,
            closed=0,
            cumulative_realized_pl=1250.0,
            cumulative_pips=18.4,
            unrealized_pl=-35.2,
        ),
        quote=MarketQuote("USD_JPY", 150.12, 150.122, 150.121),
        skipped=skipped,
        runtime_events=events,
        failure=failure,
    )


@pytest.mark.contract
def test_console_reporter_prints_one_flushable_heartbeat_with_account_totals():
    output = StringIO()
    reporter = ConsoleLiveReporter(
        SimpleNamespace(
            pair="USD_JPY",
            portfolio=_Portfolio(_result().summary),
            clock=_Clock(),
        ),
        stdout=output,
        stderr=StringIO(),
        dry_run=False,
    )

    reporter.on_result(_result())

    assert output.getvalue().splitlines() == [
        "2026-08-28T12:34:56 [TICK] pair=USD_JPY mode=LIVE mid=150.121 spread=0.2p watching=0 pending=1 open=1 realized_total=+1250.00 unrealized=-35.20 pips_total=+18.4 state=ok"
    ]


@pytest.mark.contract
def test_console_reporter_prints_candidate_diagnostics_when_tracing():
    output = StringIO()
    result = _result()
    result = LiveRunResult(
        analysis=SimpleNamespace(
            candidate_diagnostics=CandidateDiagnostics(
                raw_counts={
                    "immediate": 2,
                    "future_resist": 1,
                    "future_break": 0,
                },
                selected_counts={
                    "immediate": 0,
                    "future_resist": 1,
                    "future_break": 0,
                },
                rejected_reasons={
                    "immediate": {"immediate_conditions_not_met": 2},
                    "future_resist": {},
                    "future_break": {},
                },
            ),
        ),
        registration=result.registration,
        summary=result.summary,
        quote=result.quote,
    )
    reporter = ConsoleLiveReporter(
        SimpleNamespace(
            pair="USD_JPY",
            portfolio=_Portfolio(result.summary),
            clock=_Clock(),
        ),
        stdout=output,
        stderr=StringIO(),
        dry_run=True,
        trace_candidates=True,
    )

    reporter.on_result(result)

    assert output.getvalue().splitlines()[1] == (
        "2026-08-28T12:34:56 [CANDIDATES] "
        "raw=immediate:2,future_resist:1,future_break:0 "
        "selected=immediate:0,future_resist:1,future_break:0 "
        "rejected=immediate/immediate_conditions_not_met:2"
    )


@pytest.mark.contract
def test_console_reporter_classifies_close_reason_without_inferring_from_profit_sign():
    output = StringIO()
    event = PositionEvent(
        "trade_closed:trade-1",
        "trade_closed",
        "line-1",
        "USD_JPY",
        datetime(2026, 8, 28, 12, 34, 56),
        {
            "position": SimpleNamespace(snapshot=SimpleNamespace(trade_id="trade-1")),
            "broker_snapshot": SimpleNamespace(
                trade_id="trade-1",
                average_close_price=150.2,
                realized_pl=-10.0,
                close_reason="TAKE_PROFIT_ORDER",
            ),
        },
    )
    reporter = ConsoleLiveReporter(
        SimpleNamespace(
            pair="USD_JPY",
            portfolio=_Portfolio(_result().summary),
            clock=_Clock(),
        ),
        stdout=output,
        stderr=StringIO(),
        dry_run=False,
    )

    reporter.on_result(_result(events=(event,)))

    assert "[TP]" in output.getvalue()
    assert "reason=TAKE_PROFIT_ORDER" in output.getvalue()


@pytest.mark.contract
def test_console_reporter_prints_recoverable_failure_to_stderr():
    errors = StringIO()
    reporter = ConsoleLiveReporter(
        SimpleNamespace(
            pair="USD_JPY",
            portfolio=_Portfolio(_result().summary),
            clock=_Clock(),
        ),
        stdout=StringIO(),
        stderr=errors,
        dry_run=False,
    )

    reporter.on_result(
        _result(
            skipped=("broker_unavailable",),
            failure=LiveFailure("oanda", "temporary outage", retry_after_seconds=5),
        )
    )

    assert "[ERROR] service=oanda message=temporary outage retry=5s" in errors.getvalue()


@pytest.mark.contract
def test_console_reporter_deduplicates_runtime_and_summary_events_and_marks_dry_run():
    output = StringIO()
    event = PositionEvent(
        "order_cancelled:order-1",
        "order_cancelled",
        "line-1",
        "USD_JPY",
        datetime(2026, 8, 28, 12, 34, 56),
        {
            "position": SimpleNamespace(
                snapshot=SimpleNamespace(order_id="order-1", trade_id=None),
            ),
            "broker_snapshot": SimpleNamespace(order_id="order-1"),
        },
    )
    summary = PortfolioSummary(
        0,
        0,
        0,
        0,
        events=(event,),
    )
    result = LiveRunResult(
        None,
        RegistrationResult((), ()),
        summary=summary,
        quote=MarketQuote("USD_JPY", 150.12, 150.122, 150.121),
        runtime_events=(event,),
    )
    reporter = ConsoleLiveReporter(
        SimpleNamespace(pair="USD_JPY", portfolio=_Portfolio(summary), clock=_Clock()),
        stdout=output,
        stderr=StringIO(),
        dry_run=True,
    )

    reporter.on_result(result)

    lines = output.getvalue().splitlines()
    assert sum("[CANCEL]" in line for line in lines) == 1
    assert "mode=DRY_RUN" in lines[0]
