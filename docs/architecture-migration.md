# Architecture Migration Guide

## Source Of Truth

New production code belongs in `src/ogami_oanda`.

- `domain`: immutable business models and calculations.
- `application`: use cases, ports, scheduling, and orchestration.
- `adapters`: OANDA and legacy-dictionary boundaries.
- `strategy`: pure trading rules.

Code under `src/ogami_oanda` must not import root-level legacy modules. Root-level modules may call the new package while they remain compatibility facades.

## Legacy Boundaries

- `classPosition.py` accepts optional `oanda_factory` and `notifier` dependencies. Existing two-argument construction remains supported.
- `classPositionControl.py` remains the legacy `ActiveOrderQuery` implementation until callers migrate to `application.services.Portfolio`.
- `main_exe.py` remains the live entrypoint and delegates scheduling decisions to `application.scheduling.TradingSchedule`.
- Dictionary conversion belongs in `adapters.legacy`; new use cases accept domain models and ports.

## Experimental Code

`archive/`, root `test_*.py` scripts, `ForTestOandaClass.py`, and `tmp_rank_line_result.py` are experiments or diagnostics. They are not part of the pytest collection and must not become dependencies of `src/ogami_oanda`.

Move an experiment into production only after it has an offline test in `tests/`, a typed or documented input/output contract, and no direct network or token dependency in its domain or strategy logic.

## Local Setup And Verification

Install the package in editable mode before running root entrypoints that delegate to `src`:

```sh
.venv/bin/python -m pip install -e .
```

Run the offline migration gate:

```sh
.venv/bin/python -m compileall -q src tests
.venv/bin/python -m pytest -q -m 'not integration'
.venv/bin/python -m ruff check src tests
```

Integration tests must be explicitly marked `integration`; routine tests must run without network access.