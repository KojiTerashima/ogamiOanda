from __future__ import annotations

import argparse
import json
import os
from dataclasses import asdict
from pathlib import Path

from ogami_oanda.adapters.oanda.client import OandaClient
from ogami_oanda.adapters.oanda.execution import OandaExecutionAdapter
from ogami_oanda.adapters.oanda.market_data import OandaMarketDataAdapter
from ogami_oanda.adapters.oanda.query import OandaQueryAdapter
from ogami_oanda.application.ports.position_state import account_identity_hash
from ogami_oanda.application.services.practice_order_acceptance_service import (
    PracticeAcceptanceOperation,
    PracticeOrderAcceptanceService,
)
from ogami_oanda.infrastructure.config.loader import load_settings
from ogami_oanda.infrastructure.config.models import AppSettings
from ogami_oanda.infrastructure.runtime import SystemClock, system_sleep
from ogami_oanda.strategy.loader import StrategyPluginError, load_strategy
from ogami_oanda.domain.market.currency_pair import currency_pair


PAIRS = ("USD_JPY", "EUR_USD", "AUD_USD")


def build_service(
    settings: AppSettings,
    account_name: str,
) -> PracticeOrderAcceptanceService:
    account = settings.account(account_name)
    client = OandaClient(account)
    return PracticeOrderAcceptanceService(
        OandaMarketDataAdapter(client),
        OandaExecutionAdapter(client, include_client_extensions=True),
        OandaQueryAdapter(client),
        sleeper=system_sleep,
        clock=SystemClock().now,
        expected_account_id=client.account_id,
        require_hedging=account.require_hedging,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run destructive OANDA practice order acceptance",
    )
    parser.add_argument("--config", required=True)
    parser.add_argument("--account", default="practice")
    parser.add_argument("--execute-practice-orders", action="store_true")
    parser.add_argument("--confirm-account-id")
    parser.add_argument("--accept-small-loss", action="store_true")
    parser.add_argument("--report", default="practice-acceptance-report.json")
    parser.add_argument("--strategy-py", metavar="PATH")
    parser.add_argument("--strategy-yaml", metavar="PATH")
    arguments = parser.parse_args(argv)

    if not arguments.execute_practice_orders:
        parser.error("--execute-practice-orders is required")
    if not arguments.confirm_account_id:
        parser.error("--confirm-account-id is required")
    if not arguments.accept_small_loss:
        parser.error("--accept-small-loss is required")
    if os.environ.get("OGAMI_OANDA_ENABLE_PRACTICE_ORDERS") != "1":
        parser.error("OGAMI_OANDA_ENABLE_PRACTICE_ORDERS=1 is required")

    settings = load_settings(arguments.config)
    account = settings.account(arguments.account)
    if account.environment != "practice":
        parser.error("practice acceptance refuses non-practice accounts")
    if account.account_id != arguments.confirm_account_id:
        parser.error("confirmed account ID does not match configuration")
    if not account.account_id or not account.access_token:
        parser.error("practice account credentials are incomplete")

    has_strategy_py = arguments.strategy_py is not None
    has_strategy_yaml = arguments.strategy_yaml is not None
    if has_strategy_py != has_strategy_yaml:
        parser.error("--strategy-py and --strategy-yaml must be supplied together")

    loaded = None
    selected_pair = None
    if has_strategy_py:
        try:
            loaded = load_strategy(arguments.strategy_py, arguments.strategy_yaml)
        except StrategyPluginError as error:
            parser.error(str(error))
        try:
            selected_pair = _strategy_pair(loaded.strategy, loaded.config)
        except ValueError as error:
            parser.error(str(error))
        try:
            currency_pair(selected_pair)
        except Exception:
            parser.error(f"strategy pair is invalid: {selected_pair}")

    path = Path(arguments.report)
    account_hash = account_identity_hash(account.account_id)
    try:
        service = build_service(settings, arguments.account)
        if loaded is None:
            report = service.run(PAIRS)
        else:
            report = service.run_strategy(
                loaded.strategy,
                config=loaded.config,
                pair=selected_pair,
            )
    except Exception as error:
        operations = getattr(error, "operations", ())
        error_message = str(error)
        if account.access_token:
            error_message = error_message.replace(
                account.access_token,
                "[redacted]",
            )
        _write_report(
            path,
            {
                "success": False,
                "account_hash": account_hash,
                "operations": _serialize_operations(operations),
                "error": error_message,
            },
        )
        return 1
    _write_report(
        path,
        {
            "success": report.success,
            "account_hash": account_hash,
            "operations": _serialize_operations(report.operations),
        },
    )
    return 0


def _strategy_pair(strategy, config) -> str:
    pair = getattr(strategy, "pair", None)
    if not isinstance(pair, str) or not pair:
        pair = config.get("pair") if hasattr(config, "get") else None
    if not isinstance(pair, str) or not pair:
        raise ValueError("strategy acceptance requires a valid strategy pair")
    return pair


def _serialize_operations(
    operations: tuple[PracticeAcceptanceOperation, ...],
) -> list[dict[str, object]]:
    return [
        {
            **asdict(operation),
            "order_type": operation.order_type.value,
        }
        for operation in operations
    ]


def _write_report(path: Path, output: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(output, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    temporary.replace(path)


if __name__ == "__main__":
    raise SystemExit(main())
