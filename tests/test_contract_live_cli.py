from pathlib import Path
from types import SimpleNamespace

import pytest

import ogami_oanda.entrypoints.live as live
from ogami_oanda.application.services.position_portfolio_service import RegistrationResult
from ogami_oanda.entrypoints.live import LiveRunResult


@pytest.mark.contract
def test_console_script_is_declared_and_help_is_available(capsys):
    pyproject = (Path(__file__).parents[1] / "pyproject.toml").read_text(encoding="utf-8")

    assert 'ogami-oanda-live = "ogami_oanda.entrypoints.live:main"' in pyproject
    with pytest.raises(SystemExit) as exit_info:
        live.main(["--help"])

    assert exit_info.value.code == 0
    help_text = capsys.readouterr().out
    for option in (
        "--config",
        "--settings",
        "--account",
        "--pair",
        "--dry-run",
        "--cancel-pending-on-start",
        "--once",
        "--offline-smoke",
    ):
        assert option in help_text


@pytest.mark.contract
def test_console_once_dry_run_is_offline_testable_and_prints_plan_and_reject_reasons(
    monkeypatch,
    capsys,
):
    captured = {}
    settings = object()
    plan = SimpleNamespace(intent=SimpleNamespace(name="line-plan"))
    result = LiveRunResult(
        analysis=None,
        registration=RegistrationResult(
            ("accepted-plan",),
            (("rejected-plan", "duplicate"),),
        ),
        plans=(plan,),
    )

    class _Application:
        def run_resilient_once(self, *, dry_run=False):
            captured["resilient_dry_run"] = dry_run
            return result

        def run_forever(self, **kwargs):
            raise AssertionError("--once must not enter the live loop")

    def load(path):
        captured["config"] = path
        return settings

    def build(received_settings, **kwargs):
        captured["settings"] = received_settings
        captured["build"] = kwargs
        return _Application()

    monkeypatch.setattr(live, "load_settings", load)
    monkeypatch.setattr(live, "build_live_application", build)
    monkeypatch.setattr(
        live,
        "OandaClient",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("offline CLI smoke must not construct an OANDA client")
        ),
    )

    exit_code = live.main(
        [
            "--settings",
            "offline-settings.yaml",
            "--account",
            "secondary",
            "--pair",
            "AUD_USD",
            "--dry-run",
            "--cancel-pending-on-start",
            "--once",
        ]
    )

    assert exit_code == 0
    assert captured == {
        "config": "offline-settings.yaml",
        "settings": settings,
        "build": {
            "account_name": "secondary",
            "pair": "AUD_USD",
            "cancel_pending_on_start": True,
            "dry_run": True,
        },
        "resilient_dry_run": True,
    }
    assert capsys.readouterr().out.strip() == (
        "accepted=1 rejected=1 skipped=- plans=line-plan "
        "accepted_names=accepted-plan rejected_reasons=rejected-plan:duplicate"
    )


@pytest.mark.contract
def test_console_offline_smoke_runs_without_config_or_external_adapters(
    monkeypatch,
    capsys,
):
    monkeypatch.setattr(
        live,
        "load_settings",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("offline smoke must not load settings")
        ),
    )
    monkeypatch.setattr(
        live,
        "OandaClient",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("offline smoke must not construct OANDA")
        ),
    )

    exit_code = live.main(
        [
            "--pair",
            "AUD_USD",
            "--dry-run",
            "--once",
            "--offline-smoke",
        ]
    )

    assert exit_code == 0
    assert capsys.readouterr().out.strip() == (
        "accepted=0 rejected=0 skipped=- plans=- "
        "accepted_names=- rejected_reasons=-"
    )
