# Offline Test Baseline

Run the normal migration gate with:

```sh
.venv/bin/python -m pytest --collect-only -q
.venv/bin/python -m pytest -q -m "not integration"
.venv/bin/python -m ruff check tests
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