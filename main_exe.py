"""Compatibility entrypoint for the historical USD/JPY live runner.

The operational composition now lives in :mod:`ogami_oanda.entrypoints.live`.
This module intentionally retains ``main`` and ``run`` so existing launchers do
not need to change at the same time as the migration.
"""

import inspect
import time

import tokens as tk

from ogami_oanda.entrypoints.live import (
    LiveApplication,
    build_live_application,
)
from ogami_oanda.entrypoints.live_console import ConsoleLiveReporter
from ogami_oanda.infrastructure.config.legacy_tokens import settings_from_tokens


class main:
    def __init__(self, pair_info=None, *, application: LiveApplication | None = None, dry_run: bool = False):
        pair = getattr(pair_info, "name", None) or "USD_JPY"
        self.pair = pair
        self.application = application or build_live_application(
            settings_from_tokens(tk),
            account_name="secondary",
            pair=pair,
            # Historical main_exe cancelled pending orders during startup.
            cancel_pending_on_start=True,
            dry_run=dry_run,
        )

    def exe_manage(self, *, dry_run: bool = False):
        return self.application.run_once(dry_run=dry_run)

    def exe_loop(
        self,
        interval=1,
        wait=True,
        *,
        dry_run: bool = False,
        max_ticks: int | None = None,
        trace_candidates: bool = False,
    ):
        del interval, wait
        reporter = ConsoleLiveReporter(
            self.application,
            dry_run=dry_run,
            trace_candidates=trace_candidates,
        )
        # Keep custom legacy application doubles compatible while the
        # production LiveApplication receives the shared observer.
        run_forever = getattr(self.application, "run_forever")
        try:
            parameters = inspect.signature(run_forever).parameters
        except (TypeError, ValueError):
            return run_forever(
                dry_run=dry_run,
                sleeper=time.sleep,
                max_ticks=max_ticks,
                observer=reporter,
            )
        kwargs = {
            "dry_run": dry_run,
            "sleeper": time.sleep,
            "max_ticks": max_ticks,
        }
        if "observer" in parameters or any(
            parameter.kind is inspect.Parameter.VAR_KEYWORD
            for parameter in parameters.values()
        ):
            kwargs["observer"] = reporter
        return run_forever(**kwargs)


def run(
    pair=None,
    *,
    dry_run: bool = False,
    application: LiveApplication | None = None,
    max_ticks: int | None = None,
    trace_candidates: bool = False,
):
    runner = (
        main(application=application, dry_run=dry_run)
        if pair is None
        else main(type("Pair", (), {"name": pair})(), application=application, dry_run=dry_run)
    )
    return runner.exe_loop(
        1,
        dry_run=dry_run,
        max_ticks=max_ticks,
        trace_candidates=trace_candidates,
    )


if __name__ == "__main__":
    run()
