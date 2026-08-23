# Offline Test Baseline

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

Legacy root modules contain pre-existing lint violations. Until MIG-12 isolates
them, lint tests in MIG-00 and the new source tree plus tests from MIG-01.
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