"""Compatibility entrypoint for the historical USD/JPY live runner.

The operational composition now lives in :mod:`ogami_oanda.entrypoints.live`.
This module intentionally retains ``main`` and ``run`` so existing launchers do
not need to change at the same time as the migration.
"""

import time

import tokens as tk

from ogami_oanda.adapters.legacy.token_settings import settings_from_tokens
from ogami_oanda.entrypoints.live import LiveApplication, build_live_application


class main:
    def __init__(self, pair_info=None, *, application: LiveApplication | None = None):
        pair = getattr(pair_info, "name", None) or "USD_JPY"
        self.pair = pair
        self.application = application or build_live_application(
            settings_from_tokens(tk),
            account_name="primary",
            pair=pair,
            # Historical main_exe cancelled pending orders during startup.
            cancel_pending_on_start=True,
        )

    def exe_manage(self, *, dry_run: bool = False):
        return self.application.run_once(dry_run=dry_run)

    def exe_loop(self, interval=1, wait=True, *, dry_run: bool = False, max_ticks: int | None = None):
        del interval, wait
        return self.application.run_forever(dry_run=dry_run, sleeper=time.sleep, max_ticks=max_ticks)


def run(
    pair=None,
    *,
    dry_run: bool = False,
    application: LiveApplication | None = None,
    max_ticks: int | None = None,
):
    runner = main(application=application) if pair is None else main(type("Pair", (), {"name": pair})(), application=application)
    return runner.exe_loop(1, dry_run=dry_run, max_ticks=max_ticks)


if __name__ == "__main__":
    run()
