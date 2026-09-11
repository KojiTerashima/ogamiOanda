# Offline Test Baseline

The retained `classOanda.py` characterization dependency imports `pytz`.
It is included in the development dependencies; install the development extra
before running compatibility tests:

```sh
.venv/bin/python -m pip install -e '.[dev]'
```

This dependency setup may require package-download access. Do not substitute a
fake timezone implementation just to make the compatibility tests pass.

Run the normal migration gate with:

```sh
.venv/bin/python -m pytest --collect-only -q
.venv/bin/python -m pytest -q -m "not integration"
.venv/bin/python -m ruff check src tests
.venv/bin/python -m compileall -q src tests
```

Tests under this directory must not call OANDA, Discord, or any other network
service. `tests/conftest.py` replaces the unavailable local `tokens` module and
rejects network requests. Add an `integration` marker only to tests that are
explicitly run with credentials outside the normal offline gate.

The initial characterization suite fixes the current pair conversion, order
plan/OANDA payload, reversed candle order, line session, Position reset, and
Inspection DataFrame-boundary contracts. Extend snapshots with sanitized
captured candles before changing an affected behavior.

Legacy root modules still required by characterization contain pre-existing
lint violations; keep the lint scope at `src tests`. Unreferenced manual
root `test_*.py` scripts are archived under `archive/retired/` and are not
pytest tests. See [the archive policy](../docs/archive-policy.md).
Restore the repository-wide lint gate when the legacy facades are removed.

Credentialed read-only OANDA checks require both the integration marker and an
explicit environment gate:

```sh
OGAMI_OANDA_RUN_INTEGRATION=1 \
OGAMI_OANDA_INTEGRATION_CONFIG=config/settings.yaml \
.venv/bin/python -m pytest -q tests/integration
```

Real practice mutations are not pytest tests. Use only the isolated
`ogami-oanda-practice-acceptance` command documented in
`docs/architecture-migration.md`; it requires four explicit safety gates and
must finish with no owned pending order or open trade.

Documentation-only validation uses the standard library and does not import the
trading program:

```sh
python3 scripts/check_documentation.py
```

Add `--archives` only when verifying the retired bundles: it checks member
paths, modes, and hashes without extracting or executing old code.


Strategy layout and named-loop selection have focused offline contracts:

```sh
.venv/bin/python -m pytest -q tests/architecture/test_strategy_ownership.py tests/test_contract_live_cli.py tests/test_contract_strategy_plugins.py tests/test_matcha_strategy.py
```

They cover legacy/canonical module identity, owner dependency direction,
original startup without importing unselected Matcha, named once/loop dispatch,
argument conflicts, plugin containment, and the packaged Matcha parameters.
Neither loop dispatch test starts a real trading loop. Strategy ownership and
operator commands are documented in [the strategy guide](../src/ogami_oanda/strategy/README.md).

## Backtest Verification

```sh
.venv/bin/python -m pytest -q tests/test_backtest_*.py tests/test_contract_original_strategy_api.py
```

These offline tests cover acquisition recovery, atomic storage, rolling frames,
execution ambiguity, partial-close accounting, lifecycle integration, source-scoped
commands, CLI isolation, reproducibility, and future-input independence.
The full normal gate remains required because original and live share evaluation.

Run synthetic long-history verification separately; it is not collected by pytest:

```sh
.venv/bin/python scripts/verify_backtest_long_run.py --days 730 --output-dir results/synthetic-730-days
```

Use `--days 1` for a short benchmark of the same streaming path. See the
[backtest guide](../docs/backtest.md) for the memory limit, artifacts, approximations,
and the separate credentialed real-data acceptance boundary.
