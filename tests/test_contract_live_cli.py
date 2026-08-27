from pathlib import Path
from types import SimpleNamespace
from importlib import resources

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


@pytest.mark.contract
def test_console_requires_strategy_python_and_yaml_as_a_pair():
    with pytest.raises(SystemExit) as exit_info:
        live.main(["--strategy-py", "strategy/plugin.py"])

    assert exit_info.value.code == 2

    with pytest.raises(SystemExit) as exit_info:
        live.main(["--strategy-yaml", "strategy/plugin.yaml"])

    assert exit_info.value.code == 2


@pytest.mark.contract
def test_console_offline_smoke_rejects_strategy_options(capsys):
    with pytest.raises(SystemExit) as exit_info:
        live.main(
            [
                "--offline-smoke",
                "--dry-run",
                "--once",
                "--strategy-py",
                "strategy/plugin.py",
                "--strategy-yaml",
                "strategy/plugin.yaml",
            ]
        )

    assert exit_info.value.code == 2
    assert "cannot be combined" in capsys.readouterr().err


@pytest.mark.contract
def test_console_dispatches_trusted_strategy_loader_and_builder(monkeypatch, capsys):
    captured = {}
    settings = object()
    loaded = SimpleNamespace(strategy=object(), strategy_id="strategy-id")
    result = LiveRunResult(
        analysis=None,
        registration=RegistrationResult((), ()),
    )

    class _Application:
        def run_resilient_once(self, *, dry_run=False):
            captured["dry_run"] = dry_run
            return result

        def run_forever(self, **_kwargs):
            raise AssertionError("--once must not enter the live loop")

    monkeypatch.setattr(live, "load_settings", lambda path: settings)

    def load_strategy(strategy_py, strategy_yaml):
        captured["loader"] = (strategy_py, strategy_yaml)
        return loaded

    def build_strategy(received_settings, strategy, strategy_id, **kwargs):
        captured["builder"] = (received_settings, strategy, strategy_id, kwargs)
        return _Application()

    monkeypatch.setattr(live, "load_strategy", load_strategy)
    monkeypatch.setattr(live, "build_strategy_live_application", build_strategy)

    assert live.main(
        [
            "--config",
            "settings.yaml",
            "--pair",
            "USD_JPY",
            "--dry-run",
            "--once",
            "--strategy-py",
            "strategy/plugin.py",
            "--strategy-yaml",
            "strategy/plugin.yaml",
        ]
    ) == 0

    assert captured == {
        "loader": ("strategy/plugin.py", "strategy/plugin.yaml"),
        "builder": (
            settings,
            loaded.strategy,
            "strategy-id",
            {
                "account_name": "primary",
                "pair": "USD_JPY",
                "cancel_pending_on_start": False,
                "dry_run": True,
            },
        ),
        "dry_run": True,
    }
    assert capsys.readouterr().out.strip() == (
        "accepted=0 rejected=0 skipped=- plans=- "
        "accepted_names=- rejected_reasons=-"
    )


@pytest.mark.contract
def test_console_surfaces_loader_containment_error_as_argparse_error(monkeypatch, capsys):
    def reject(_strategy_py, _strategy_yaml):
        raise live.StrategyPluginError(
            "strategy Python path must resolve within package strategy directory"
        )

    monkeypatch.setattr(live, "load_settings", lambda _path: object())
    monkeypatch.setattr(live, "load_strategy", reject)

    with pytest.raises(SystemExit) as exit_info:
        live.main(
            [
                "--config",
                "settings.yaml",
                "--strategy-py",
                "../outside.py",
                "--strategy-yaml",
                "strategy/plugin.yaml",
            ]
        )

    assert exit_info.value.code == 2
    assert "must resolve within package" in capsys.readouterr().err


@pytest.mark.contract
def test_matcha_yaml_is_a_package_resource_and_contains_no_secret_hooks():
    package = resources.files("ogami_oanda.strategy")
    yaml_text = package.joinpath("matcha_param2019_oanda.yaml").read_text(encoding="utf-8")

    assert "pair: USD_JPY" in yaml_text
    assert "TODO(notification-integration)" in yaml_text
    assert "webhook" not in yaml_text.lower()
    assert "discord" not in yaml_text.lower()


@pytest.mark.contract
def test_strategy_operator_documentation_covers_boundary_invocation_and_safety():
    documentation = (
        Path(__file__).parents[1] / "docs" / "architecture-migration.md"
    ).read_text(encoding="utf-8")

    for phrase in (
        "--strategy-py",
        "--strategy-yaml",
        "strategy plugin practice acceptance",
        "trusted",
        "USD_JPY",
        "quarant",
        "dry-run",
        "secret",
        "matcha_param2019_oanda.yaml",
    ):
        assert phrase.lower() in documentation.lower()
