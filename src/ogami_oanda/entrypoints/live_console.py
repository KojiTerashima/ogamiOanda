from __future__ import annotations

import sys
from collections.abc import Mapping
from typing import IO, TYPE_CHECKING, Any

from ogami_oanda.domain.market.currency_pair import currency_pair

if TYPE_CHECKING:
    from ogami_oanda.entrypoints.live import LiveRunResult


_STOP_REASONS = {
    "STOP_LOSS_ORDER",
    "GUARANTEED_STOP_LOSS_ORDER",
    "TRAILING_STOP_LOSS_ORDER",
}
_CANDIDATE_MODES = ("immediate", "future_resist", "future_break")


def format_candidate_diagnostics(diagnostics: Any) -> str:
    raw = ",".join(
        f"{mode}:{int(diagnostics.raw_counts.get(mode, 0))}"
        for mode in _CANDIDATE_MODES
    )
    selected = ",".join(
        f"{mode}:{int(diagnostics.selected_counts.get(mode, 0))}"
        for mode in _CANDIDATE_MODES
    )
    rejected = ",".join(
        f"{mode}/{reason}:{int(count)}"
        for mode in _CANDIDATE_MODES
        for reason, count in diagnostics.rejected_reasons.get(mode, {}).items()
        if count
    ) or "-"
    return f"raw={raw} selected={selected} rejected={rejected}"


class ConsoleLiveReporter:
    """Render one completed live tick and its typed runtime events.

    The reporter intentionally depends only on the application-shaped object
    passed by the two production entrypoints.  This keeps the domain and
    service layers free of presentation concerns and makes the output easy to
    capture in contract tests.
    """

    def __init__(
        self,
        application: Any,
        *,
        stdout: IO[str] | None = None,
        stderr: IO[str] | None = None,
        dry_run: bool = False,
        trace_candidates: bool = False,
    ) -> None:
        self.application = application
        self.stdout = stdout if stdout is not None else sys.stdout
        self.stderr = stderr if stderr is not None else sys.stderr
        self.dry_run = dry_run
        self.trace_candidates = trace_candidates
        self._seen_event_ids: set[str] = set()

    def on_result(self, result: "LiveRunResult") -> None:
        result_summary = getattr(result, "summary", None)
        portfolio = getattr(self.application, "portfolio", None)
        live_summary = (
            portfolio.summary()
            if portfolio is not None and callable(getattr(portfolio, "summary", None))
            else None
        )
        # The service summary is the end-of-tick state, while result.summary
        # may be the pre-registration lifecycle summary. Keep the latter for
        # its event/command payload but always heartbeat the latest counts.
        summary = live_summary or result_summary
        event_summary = result_summary or summary
        quote = getattr(result, "quote", None)
        pair_name = getattr(quote, "pair", None) or getattr(self.application, "pair", "-")
        pair = self._pair(pair_name)
        now = self._now()
        mid = self._number(getattr(quote, "mid", None), pair)
        spread = "-"
        if quote is not None:
            spread = self._number(pair.price_to_pips(float(quote.spread)), None)
        watching = getattr(summary, "watching", 0) if summary is not None else 0
        pending = getattr(summary, "pending", 0) if summary is not None else 0
        open_count = getattr(summary, "open", 0) if summary is not None else 0
        realized = (
            getattr(summary, "cumulative_realized_pl", getattr(summary, "realized_total", 0.0))
            if summary is not None
            else 0.0
        )
        unrealized = (
            getattr(summary, "unrealized_pl", getattr(summary, "current_unrealized_pl", 0.0))
            if summary is not None
            else 0.0
        )
        pips = (
            getattr(summary, "cumulative_pips", getattr(summary, "pips_total", 0.0))
            if summary is not None
            else 0.0
        )
        skipped = getattr(result, "skipped", ())
        state = ",".join(skipped) if skipped else "ok"
        mode = "DRY_RUN" if self.dry_run else "LIVE"
        self._print(
            self.stdout,
            f"{now} [TICK] pair={pair_name} mode={mode} mid={mid} "
            f"spread={spread + 'p' if spread != '-' else '-'} watching={watching} pending={pending} open={open_count} "
            f"realized_total={float(realized):+.2f} unrealized={float(unrealized):+.2f} "
            f"pips_total={float(pips):+.1f} state={state}",
        )
        analysis = getattr(result, "analysis", None)
        diagnostics = getattr(analysis, "candidate_diagnostics", None)
        if self.trace_candidates and diagnostics is not None:
            self._print(
                self.stdout,
                f"{now} [CANDIDATES] {format_candidate_diagnostics(diagnostics)}",
            )

        emitted_names: set[str] = set()
        emitted_reject_names: set[str] = set()
        emitted_cancel_names: set[str] = set()
        emitted_command_keys: set[tuple[str, str | None]] = set()
        raw_events = tuple(getattr(result, "runtime_events", ()))
        if event_summary is not None:
            raw_events += tuple(getattr(event_summary, "events", ()))
        for event in raw_events:
            event_id = str(getattr(event, "event_id", ""))
            if event_id and event_id in self._seen_event_ids:
                continue
            if event_id:
                self._seen_event_ids.add(event_id)
            name = getattr(event, "name", "-")
            emitted_names.add(name)
            kind = getattr(event, "kind", "")
            if kind == "order_rejected":
                emitted_reject_names.add(name)
            elif kind == "order_cancelled":
                emitted_cancel_names.add(name)
            event_data = getattr(event, "data", {}) or {}
            broker_snapshot = event_data.get("broker_snapshot")
            event_position = getattr(event_data.get("position"), "snapshot", None)
            event_snapshot = getattr(broker_snapshot, "trade_id", None)
            event_snapshot = event_snapshot or getattr(broker_snapshot, "order_id", None)
            event_snapshot = event_snapshot or getattr(event_position, "trade_id", None)
            event_snapshot = event_snapshot or getattr(event_position, "order_id", None)
            if kind == "stop_loss_amended":
                emitted_command_keys.add(("amend_stop_loss", event_snapshot))
            elif kind == "order_cancelled":
                emitted_command_keys.add(("cancel_order", event_snapshot))
            elif kind == "trade_close_requested":
                emitted_command_keys.add(("close_trade", event_snapshot))
            elif kind == "trade_reduced":
                emitted_command_keys.add(("reduce_trade", event_snapshot))
            self._print_event(event, pair)

        # A dry-run has no new broker order acknowledgement. Plans are
        # rendered explicitly so they cannot be mistaken for live orders.
        registration = getattr(result, "registration", None)
        for plan in getattr(result, "plans", ()):
            if self.dry_run:
                self._print_plan(plan, pair)
            elif plan.intent.name in getattr(registration, "accepted", ()) and plan.intent.name not in emitted_names:
                self._print_order_from_plan(plan, pair)
        for name, reason in getattr(registration, "rejected", ()):
            if name in emitted_reject_names or name in emitted_cancel_names:
                continue
            self._print(
                self.stdout,
                f"{now} [REJECT] {self._mode_field()}name={name} "
                f"pair={pair.name} reason={reason}",
            )

        summary_commands = (
            getattr(event_summary, "commands", ()) if event_summary is not None else ()
        )
        strategy_result = getattr(result, "strategy_command_result", None)
        strategy_commands = (
            getattr(strategy_result, "executed", ())
            if strategy_result is not None
            else ()
        )
        for command in (*summary_commands, *strategy_commands):
            command_key = (
                getattr(command, "action", ""),
                getattr(command, "reference_id", None),
            )
            if command_key in emitted_command_keys:
                continue
            emitted_command_keys.add(command_key)
            self._print_command(command, pair)

        if strategy_result is not None:
            for reason in getattr(strategy_result, "rejected", ()):
                self._print(
                    self.stdout,
                    f"{now} [REJECT] {self._mode_field()}"
                    f"name=strategy pair={pair.name} reason={reason}",
                )

        failure = getattr(result, "failure", None)
        if failure is not None:
            retry = self._retry_text(getattr(failure, "retry_after_seconds", None))
            self._print(
                self.stderr,
                f"{now} [ERROR] service={getattr(failure, 'service', 'unknown')} "
                f"message={getattr(failure, 'message', '')} retry={retry}",
            )
        elif "broker_reconciliation" in skipped or (
            strategy_result is not None
            and getattr(strategy_result, "unresolved", False)
        ):
            self._print(
                self.stderr,
                f"{now} [ERROR] service=portfolio "
                "message=broker_reconciliation retry=-",
            )

    # Friendly aliases for integrations that call the observer a reporter.
    report = on_result
    on_tick = on_result

    def on_error(self, error: BaseException) -> None:
        now = self._now()
        self._print(
            self.stderr,
            f"{now} [FATAL] type={type(error).__name__} message={error}",
        )

    def _print_event(self, event: Any, pair: Any) -> None:
        kind = getattr(event, "kind", "")
        data = getattr(event, "data", {}) or {}
        position = data.get("position")
        snapshot = getattr(position, "snapshot", position)
        broker = data.get("broker_snapshot", snapshot)
        if kind in {"order_submitted", "trade_opened", "order_rejected"}:
            tag = "FILL" if kind == "trade_opened" else "REJECT" if kind == "order_rejected" else "ORDER"
            fields = self._order_fields(position, broker, pair)
            if kind == "order_rejected":
                reason = data.get("reason") or getattr(
                    getattr(position, "runtime", None),
                    "submission_reason",
                    "",
                )
                if not reason:
                    reason = getattr(broker, "reason", "")
                if reason:
                    fields += f" reason={reason}"
            self._print(
                self.stdout,
                f"{self._timestamp(getattr(event, 'occurred_at', self._now()))} [{tag}] "
                f"{self._mode_field()}"
                + fields,
            )
            return
        if kind == "trade_reduced":
            self._print(
                self.stdout,
                f"{self._timestamp(getattr(event, 'occurred_at', self._now()))} [CLOSE] "
                f"{self._mode_field()}"
                f"name={getattr(event, 'name', '-')} pair={getattr(event, 'pair', pair.name)} "
                f"trade_id={self._value(getattr(broker, 'trade_id', None) or getattr(snapshot, 'trade_id', None))} "
                f"remaining_units={getattr(snapshot, 'units', 0)} reason={data.get('reason', '')}",
            )
            return
        if kind in {"trade_closed", "trade_close_requested"}:
            if kind == "trade_close_requested":
                self._print(
                    self.stdout,
                    f"{self._timestamp(getattr(event, 'occurred_at', self._now()))} [CLOSE] "
                    f"{self._mode_field()}"
                    f"name={getattr(event, 'name', '-')} pair={getattr(event, 'pair', pair.name)} "
                    f"trade_id={self._value(getattr(broker, 'trade_id', None) or getattr(snapshot, 'trade_id', None))} "
                    f"reason={data.get('reason', '')}",
                )
                return
            raw_reason = str(
                getattr(broker, "close_reason", "")
                or getattr(snapshot, "close_reason", "")
                or "UNKNOWN"
            )
            tag = "TP" if raw_reason == "TAKE_PROFIT_ORDER" else "LC" if raw_reason in _STOP_REASONS else "CLOSE"
            realized = getattr(broker, "realized_pl", getattr(snapshot, "realized_pl", 0.0))
            self._print(
                self.stdout,
                f"{self._timestamp(getattr(event, 'occurred_at', self._now()))} [{tag}] "
                f"{self._mode_field()}"
                f"name={getattr(event, 'name', '-') } pair={getattr(event, 'pair', pair.name)} "
                f"trade_id={self._value(getattr(broker, 'trade_id', None) or getattr(snapshot, 'trade_id', None))} "
                f"reason={raw_reason} realized={float(realized):+.2f}",
            )
            return
        if kind == "order_cancelled":
            self._print(
                self.stdout,
                f"{self._timestamp(getattr(event, 'occurred_at', self._now()))} [CANCEL] "
                f"{self._mode_field()}"
                f"name={getattr(event, 'name', '-')} pair={getattr(event, 'pair', pair.name)} "
                f"order_id={self._value(getattr(broker, 'order_id', None) or getattr(snapshot, 'order_id', None))}",
            )
            return
        if kind in {"stop_loss_amended", "lc_updated", "lc_changed"}:
            stop_loss = getattr(broker, "current_stop_loss", None)
            if stop_loss is None:
                stop_loss = getattr(snapshot, "current_stop_loss", None)
            self._print(
                self.stdout,
                f"{self._timestamp(getattr(event, 'occurred_at', self._now()))} [LC_UPDATE] "
                f"{self._mode_field()}"
                f"name={getattr(event, 'name', '-')} pair={getattr(event, 'pair', pair.name)} "
                f"trade_id={self._value(getattr(broker, 'trade_id', None) or getattr(snapshot, 'trade_id', None))} "
                f"lc={self._value(stop_loss)} reason={data.get('reason', '')}",
            )
            return
        self._print(
            self.stdout,
            f"{self._timestamp(getattr(event, 'occurred_at', self._now()))} [EVENT] kind={kind} "
            f"{self._mode_field()}"
            f"name={getattr(event, 'name', '-')} pair={getattr(event, 'pair', pair.name)}",
        )

    def _print_plan(self, plan: Any, pair: Any) -> None:
        self._print(
            self.stdout,
            f"{self._now()} [PLAN] mode=DRY_RUN "
            + self._plan_fields(plan, pair),
        )

    def _print_order_from_plan(self, plan: Any, pair: Any) -> None:
        self._print(self.stdout, f"{self._now()} [ORDER] " + self._plan_fields(plan, pair))

    def _print_command(self, command: Any, pair: Any) -> None:
        action = getattr(command, "action", "")
        tag = (
            "LC_UPDATE"
            if action == "amend_stop_loss"
            else "CANCEL"
            if action == "cancel_order"
            else "CLOSE"
            if action in {"close_trade", "reduce_trade"}
            else "COMMAND"
        )
        details = [
            f"pair={pair.name}",
            f"ref={self._value(getattr(command, 'reference_id', None))}",
            f"reason={getattr(command, 'reason', '')}",
        ]
        stop = getattr(command, "stop_loss_price", None)
        if stop is not None:
            details.append(f"lc={stop}")
        command_data = getattr(command, "data", None)
        if isinstance(command_data, Mapping) and command_data.get("units") is not None:
            details.append(f"units={command_data['units']}")
        self._print(
            self.stdout,
            f"{self._now()} [{tag}] {self._mode_field()}" + " ".join(details),
        )

    def _order_fields(self, position: Any, broker: Any, pair: Any) -> str:
        snapshot = getattr(position, "snapshot", position)
        runtime = getattr(position, "runtime", None)
        plan = getattr(runtime, "order_plan", None)
        if plan is not None:
            return self._plan_fields(plan, pair, name=getattr(snapshot, "name", "-")) + " " + " ".join(
                (
                    f"order_id={self._value(getattr(broker, 'order_id', None) or getattr(snapshot, 'order_id', None))}",
                    f"trade_id={self._value(getattr(broker, 'trade_id', None) or getattr(snapshot, 'trade_id', None))}",
                )
            )
        direction = getattr(snapshot, "direction", None) or getattr(runtime, "direction", None)
        side = "BUY" if direction is not None and int(direction) > 0 else "SELL" if direction is not None else "-"
        return (
            f"name={getattr(snapshot, 'name', '-')} pair={getattr(snapshot, 'pair', pair.name)} "
            f"side={side} type=- units={getattr(snapshot, 'units', 0)} "
            f"target={self._value(getattr(snapshot, 'target_price', None))} tp=- lc={self._value(getattr(snapshot, 'current_stop_loss', None))} "
            f"order_id={self._value(getattr(broker, 'order_id', None) or getattr(snapshot, 'order_id', None))} "
            f"trade_id={self._value(getattr(broker, 'trade_id', None) or getattr(snapshot, 'trade_id', None))}"
        )

    def _plan_fields(self, plan: Any, pair: Any, *, name: str | None = None) -> str:
        intent = plan.intent
        side = "BUY" if int(intent.direction.value) > 0 else "SELL"
        return (
            f"name={name or intent.name} pair={intent.pair or pair.name} side={side} "
            f"type={intent.order_type.value} units={intent.units} target={plan.target_price} "
            f"tp={plan.take_profit_price} lc={plan.stop_loss_price} "
            f"client_id={self._value(getattr(plan.broker_request, 'client_reference', None))}"
        )

    @staticmethod
    def _pair(name: str) -> Any:
        try:
            return currency_pair(name)
        except (KeyError, ValueError):
            return type(
                "Pair",
                (),
                {
                    "name": name,
                    "round_keta": 5,
                    "round_price": lambda _self, value: round(value, 5),
                    "price_to_pips": lambda _self, value: value,
                },
            )()

    def _now(self) -> str:
        clock = getattr(self.application, "clock", None)
        if clock is None or not hasattr(clock, "now"):
            return "-"
        try:
            now = clock.now()
        except Exception:
            return "-"
        return now.isoformat()

    @staticmethod
    def _timestamp(value: Any) -> str:
        return value.isoformat() if hasattr(value, "isoformat") else str(value)

    @staticmethod
    def _number(value: Any, pair: Any) -> str:
        if value is None:
            return "-"
        if pair is not None:
            value = pair.round_price(float(value))
        return str(value)

    @staticmethod
    def _value(value: Any) -> str:
        return "-" if value is None or value == "" else str(value)

    @staticmethod
    def _retry_text(value: Any) -> str:
        if value is None:
            return "-"
        number = float(value)
        text = str(int(number)) if number.is_integer() else str(number)
        return f"{text}s"

    def _mode_field(self) -> str:
        return "mode=DRY_RUN " if self.dry_run else ""

    @staticmethod
    def _print(stream: IO[str], line: str) -> None:
        print(line, file=stream, flush=True)


# Kept as a public alias for callers that prefer the shorter name.
LiveConsoleReporter = ConsoleLiveReporter
ConsoleReporter = ConsoleLiveReporter


from ogami_oanda.entrypoints.live import LiveFailure, LiveRunObserver  # noqa: E402  (compatibility re-export)

__all__ = [
    "ConsoleLiveReporter",
    "LiveConsoleReporter",
    "ConsoleReporter",
    "LiveFailure",
    "LiveRunObserver",
    "format_candidate_diagnostics",
]
