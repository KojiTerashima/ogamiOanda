from __future__ import annotations

import json

import pytest

import ogami_oanda.entrypoints.practice_acceptance as cli
from ogami_oanda.application.services.practice_order_acceptance_service import (
    PracticeAcceptanceError,
    PracticeAcceptanceOperation,
    PracticeAcceptanceReport,
)
from ogami_oanda.domain.orders.models import OrderType
from ogami_oanda.infrastructure.config.models import (
    AppSettings,
    RuntimeAccountConfig,
)


@pytest.mark.contract
@pytest.mark.parametrize(
    "argv",
    [
        [],
        ["--execute-practice-orders"],
        [
            "--execute-practice-orders",
            "--confirm-account-id",
            "practice-id",
        ],
        [
            "--execute-practice-orders",
            "--confirm-account-id",
            "practice-id",
            "--accept-small-loss",
        ],
    ],
)
def test_practice_acceptance_cli_requires_all_explicit_gates(monkeypatch, argv):
    monkeypatch.delenv("OGAMI_OANDA_ENABLE_PRACTICE_ORDERS", raising=False)
    monkeypatch.setattr(
        cli,
        "build_service",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("unsafe arguments must not build OANDA adapters")
        ),
    )

    with pytest.raises(SystemExit) as exit_info:
        cli.main(["--config", "settings.yaml", *argv])

    assert exit_info.value.code == 2


@pytest.mark.contract
def test_practice_acceptance_cli_rejects_live_or_mismatched_account(monkeypatch):
    live_settings = AppSettings(
        {"practice": RuntimeAccountConfig("practice-id", "token", "live")}
    )
    monkeypatch.setenv("OGAMI_OANDA_ENABLE_PRACTICE_ORDERS", "1")
    monkeypatch.setattr(cli, "load_settings", lambda _path: live_settings)

    with pytest.raises(SystemExit) as live_exit:
        cli.main(
            [
                "--config",
                "settings.yaml",
                "--account",
                "practice",
                "--execute-practice-orders",
                "--confirm-account-id",
                "practice-id",
                "--accept-small-loss",
            ]
        )
    assert live_exit.value.code == 2

    practice_settings = AppSettings(
        {"practice": RuntimeAccountConfig("practice-id", "token", "practice")}
    )
    monkeypatch.setattr(cli, "load_settings", lambda _path: practice_settings)
    with pytest.raises(SystemExit) as mismatch_exit:
        cli.main(
            [
                "--config",
                "settings.yaml",
                "--account",
                "practice",
                "--execute-practice-orders",
                "--confirm-account-id",
                "wrong-id",
                "--accept-small-loss",
            ]
        )
    assert mismatch_exit.value.code == 2


@pytest.mark.contract
def test_practice_acceptance_cli_runs_service_and_writes_secret_free_report(
    monkeypatch,
    tmp_path,
):
    settings = AppSettings(
        {"practice": RuntimeAccountConfig("practice-id", "secret-token", "practice")}
    )
    report = PracticeAcceptanceReport(
        True,
        (
            PracticeAcceptanceOperation(
                "USD_JPY",
                OrderType.MARKET,
                "order-1",
                "trade-1",
                True,
            ),
        ),
    )

    class _Service:
        def run(self, pairs):
            assert pairs == ("USD_JPY", "EUR_USD", "AUD_USD")
            return report

    monkeypatch.setenv("OGAMI_OANDA_ENABLE_PRACTICE_ORDERS", "1")
    monkeypatch.setattr(cli, "load_settings", lambda _path: settings)
    monkeypatch.setattr(cli, "build_service", lambda _settings, _account: _Service())
    report_path = tmp_path / "report.json"

    exit_code = cli.main(
        [
            "--config",
            "settings.yaml",
            "--account",
            "practice",
            "--execute-practice-orders",
            "--confirm-account-id",
            "practice-id",
            "--accept-small-loss",
            "--report",
            str(report_path),
        ]
    )

    assert exit_code == 0
    written = json.loads(report_path.read_text(encoding="utf-8"))
    assert written["success"] is True
    assert written["account_hash"]
    assert written["operations"][0]["trade_id"] == "trade-1"
    assert "secret-token" not in report_path.read_text(encoding="utf-8")


@pytest.mark.contract
def test_practice_acceptance_cli_writes_failure_report_and_returns_nonzero(
    monkeypatch,
    tmp_path,
):
    settings = AppSettings(
        {"practice": RuntimeAccountConfig("practice-id", "secret-token", "practice")}
    )

    class _Service:
        def run(self, _pairs):
            raise PracticeAcceptanceError("market unavailable")

    monkeypatch.setenv("OGAMI_OANDA_ENABLE_PRACTICE_ORDERS", "1")
    monkeypatch.setattr(cli, "load_settings", lambda _path: settings)
    monkeypatch.setattr(cli, "build_service", lambda _settings, _account: _Service())
    report_path = tmp_path / "failed-report.json"

    exit_code = cli.main(
        [
            "--config",
            "settings.yaml",
            "--account",
            "practice",
            "--execute-practice-orders",
            "--confirm-account-id",
            "practice-id",
            "--accept-small-loss",
            "--report",
            str(report_path),
        ]
    )

    assert exit_code == 1
    written = json.loads(report_path.read_text(encoding="utf-8"))
    assert written["success"] is False
    assert written["account_hash"]
    assert written["error"] == "market unavailable"
    assert "secret-token" not in report_path.read_text(encoding="utf-8")


@pytest.mark.contract
def test_practice_acceptance_cli_reports_unexpected_failure_with_partial_operations(
    monkeypatch,
    tmp_path,
):
    settings = AppSettings(
        {"practice": RuntimeAccountConfig("practice-id", "secret-token", "practice")}
    )
    partial = (
        PracticeAcceptanceOperation(
            "USD_JPY",
            OrderType.LIMIT,
            "order-1",
            None,
            True,
        ),
    )

    class _UnexpectedFailure(RuntimeError):
        operations = partial

    class _Service:
        def run(self, _pairs):
            raise _UnexpectedFailure("broker failed with secret-token")

    monkeypatch.setenv("OGAMI_OANDA_ENABLE_PRACTICE_ORDERS", "1")
    monkeypatch.setattr(cli, "load_settings", lambda _path: settings)
    monkeypatch.setattr(cli, "build_service", lambda _settings, _account: _Service())
    report_path = tmp_path / "unexpected-failure.json"

    exit_code = cli.main(
        [
            "--config",
            "settings.yaml",
            "--account",
            "practice",
            "--execute-practice-orders",
            "--confirm-account-id",
            "practice-id",
            "--accept-small-loss",
            "--report",
            str(report_path),
        ]
    )

    assert exit_code == 1
    written = json.loads(report_path.read_text(encoding="utf-8"))
    assert written["operations"][0]["order_id"] == "order-1"
    assert written["error"] == "broker failed with [redacted]"
    assert "secret-token" not in report_path.read_text(encoding="utf-8")


@pytest.mark.contract
def test_practice_acceptance_console_script_is_declared():
    pyproject = open("pyproject.toml", encoding="utf-8").read()

    assert (
        'ogami-oanda-practice-acceptance = '
        '"ogami_oanda.entrypoints.practice_acceptance:main"'
    ) in pyproject


@pytest.mark.contract
def test_strategy_options_still_require_all_destructive_gates(monkeypatch):
    monkeypatch.delenv("OGAMI_OANDA_ENABLE_PRACTICE_ORDERS", raising=False)
    monkeypatch.setattr(
        cli,
        "build_service",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("unsafe strategy arguments must not build adapters")
        ),
    )

    with pytest.raises(SystemExit) as exit_info:
        cli.main(
            [
                "--config",
                "settings.yaml",
                "--strategy-py",
                "strategy.py",
                "--strategy-yaml",
                "strategy.yaml",
            ]
        )

    assert exit_info.value.code == 2


@pytest.mark.contract
def test_strategy_cli_loads_after_gates_and_dispatches_service(monkeypatch, tmp_path):
    settings = AppSettings(
        {"practice": RuntimeAccountConfig("practice-id", "secret-token", "practice")}
    )
    loaded = type("Loaded", (), {"strategy": object(), "config": {"pair": "USD_JPY"}})()
    calls = []

    class _Service:
        def run_strategy(self, strategy, *, config=None, pair=None):
            calls.append((strategy, config, pair))
            return report

    report = PracticeAcceptanceReport(
        True,
        (PracticeAcceptanceOperation("USD_JPY", OrderType.LIMIT, "o", None, True),),
    )
    monkeypatch.setenv("OGAMI_OANDA_ENABLE_PRACTICE_ORDERS", "1")
    monkeypatch.setattr(cli, "load_settings", lambda _path: settings)
    monkeypatch.setattr(cli, "load_strategy", lambda py, yaml: loaded)
    monkeypatch.setattr(cli, "build_service", lambda *_args, **_kwargs: _Service())
    report_path = tmp_path / "strategy-report.json"

    exit_code = cli.main(
        [
            "--config", "settings.yaml", "--account", "practice",
            "--execute-practice-orders", "--confirm-account-id", "practice-id",
            "--accept-small-loss", "--strategy-py", "strategy.py",
            "--strategy-yaml", "strategy.yaml", "--report", str(report_path),
        ]
    )

    assert exit_code == 0
    assert calls == [(loaded.strategy, loaded.config, "USD_JPY")]


@pytest.mark.contract
def test_strategy_loader_error_is_reported_as_argparse_error_before_adapters(monkeypatch):
    from ogami_oanda.strategy.loader import StrategyPluginError

    settings = AppSettings(
        {"practice": RuntimeAccountConfig("practice-id", "secret-token", "practice")}
    )
    monkeypatch.setenv("OGAMI_OANDA_ENABLE_PRACTICE_ORDERS", "1")
    monkeypatch.setattr(cli, "load_settings", lambda _path: settings)
    monkeypatch.setattr(
        cli,
        "load_strategy",
        lambda *_args: (_ for _ in ()).throw(StrategyPluginError("bad plugin")),
    )
    monkeypatch.setattr(
        cli,
        "build_service",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("loader errors must precede adapter construction")
        ),
    )

    with pytest.raises(SystemExit) as exit_info:
        cli.main(
            [
                "--config", "settings.yaml", "--account", "practice",
                "--execute-practice-orders", "--confirm-account-id", "practice-id",
                "--accept-small-loss", "--strategy-py", "strategy.py",
                "--strategy-yaml", "strategy.yaml",
            ]
        )

    assert exit_info.value.code == 2


@pytest.mark.contract
def test_strategy_pair_error_is_reported_before_adapter_construction(monkeypatch):
    settings = AppSettings(
        {"practice": RuntimeAccountConfig("practice-id", "secret-token", "practice")}
    )
    loaded = type("Loaded", (), {"strategy": object(), "config": {"pair": "BAD"}})()
    monkeypatch.setenv("OGAMI_OANDA_ENABLE_PRACTICE_ORDERS", "1")
    monkeypatch.setattr(cli, "load_settings", lambda _path: settings)
    monkeypatch.setattr(cli, "load_strategy", lambda *_args: loaded)
    monkeypatch.setattr(
        cli,
        "build_service",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("invalid strategy pair must precede adapter construction")
        ),
    )

    with pytest.raises(SystemExit) as exit_info:
        cli.main(
            [
                "--config", "settings.yaml", "--account", "practice",
                "--execute-practice-orders", "--confirm-account-id", "practice-id",
                "--accept-small-loss", "--strategy-py", "strategy.py",
                "--strategy-yaml", "strategy.yaml",
            ]
        )

    assert exit_info.value.code == 2
