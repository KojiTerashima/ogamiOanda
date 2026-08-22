from types import SimpleNamespace

import pytest

import main_exe
import main_exe_aud
import main_exe_euro


class _Application:
    def __init__(self):
        self.forever_calls = []

    def run_once(self, *, dry_run=False):
        return dry_run

    def run_forever(self, *, dry_run=False, sleeper=None, max_ticks=None):
        self.forever_calls.append((dry_run, max_ticks))
        return ()


@pytest.mark.contract
def test_legacy_runner_preserves_secondary_account_and_dry_run_startup_safety(monkeypatch):
    captured = {}
    application = _Application()

    def build(settings, **kwargs):
        captured.update(kwargs)
        return application

    monkeypatch.setattr(main_exe, "build_live_application", build)

    runner = main_exe.main(SimpleNamespace(name="EUR_USD"), dry_run=True)

    assert runner.application is application
    assert captured == {
        "account_name": "secondary",
        "pair": "EUR_USD",
        "cancel_pending_on_start": True,
        "dry_run": True,
    }


@pytest.mark.contract
def test_legacy_run_forwards_pair_independent_dry_run_to_finite_loop():
    application = _Application()

    assert main_exe.run("AUD_USD", dry_run=True, application=application, max_ticks=1) == ()
    assert application.forever_calls == [(True, 1)]


@pytest.mark.contract
def test_pair_specific_legacy_launchers_delegate_by_pair_argument(monkeypatch):
    calls = []

    def capture(pair, **kwargs):
        calls.append((pair, kwargs))

    monkeypatch.setattr(main_exe_euro, "run", capture)
    monkeypatch.setattr(main_exe_aud, "run", capture)

    euro_application = _Application()
    aud_application = _Application()
    assert (
        main_exe_euro.main(
            dry_run=True,
            application=euro_application,
            max_ticks=1,
        )
        is None
    )
    assert (
        main_exe_aud.main(
            dry_run=True,
            application=aud_application,
            max_ticks=2,
        )
        is None
    )
    assert calls == [
        (
            "EUR_USD",
            {
                "dry_run": True,
                "application": euro_application,
                "max_ticks": 1,
            },
        ),
        (
            "AUD_USD",
            {
                "dry_run": True,
                "application": aud_application,
                "max_ticks": 2,
            },
        ),
    ]


@pytest.mark.contract
@pytest.mark.parametrize(
    ("pair_info", "expected_pair"),
    [
        (None, "USD_JPY"),
        (SimpleNamespace(name="EUR_USD"), "EUR_USD"),
        (SimpleNamespace(name="AUD_USD"), "AUD_USD"),
    ],
)
def test_all_three_legacy_pairs_build_the_same_src_composition(
    monkeypatch,
    pair_info,
    expected_pair,
):
    captured = {}
    application = _Application()

    def build(settings, **kwargs):
        captured.update(kwargs)
        return application

    monkeypatch.setattr(main_exe, "build_live_application", build)

    runner = main_exe.main(pair_info, dry_run=True)

    assert runner.application is application
    assert captured == {
        "account_name": "secondary",
        "pair": expected_pair,
        "cancel_pending_on_start": True,
        "dry_run": True,
    }
