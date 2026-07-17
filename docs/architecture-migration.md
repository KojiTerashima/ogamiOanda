# Architecture Migration Guide

## Source Of Truth

New production code belongs in `src/ogami_oanda`.

- `domain`: immutable business models and calculations.
- `application`: use cases, ports, scheduling, and orchestration.
- `adapters`: OANDA and legacy-dictionary boundaries.
- `strategy`: pure trading rules.
- `infrastructure`: settings loading and runtime configuration.
- `entrypoints`: composition roots and command-line execution.

Code under `src/ogami_oanda` must not import root-level legacy modules. Root-level modules may call the new package while they remain compatibility facades.

`domain` and `strategy` must not import `tokens`, `requests`, `oandapyV20`, CSV files, or notification implementations. Network and filesystem work belongs in adapters; application services depend on ports.

## Migration Map

| Legacy surface | Source-of-truth replacement | Compatibility status |
| --- | --- | --- |
| `classOanda.py` indicator helpers | `domain.analysis.indicators` | Public helpers delegate to `src`. |
| `classCandleAnalysis.py` metadata | `domain.analysis.candle_meta` | `CandleMeta` delegates to `src`. |
| `classCandlePeaks.py` | `domain.analysis.peaks` | Public peak APIs delegate to `src`. |
| `fLineAnalysis.py` grouping and candidate filtering | `domain.analysis.lines`, `strategy.line.coordinator` | Grouping and candidate-building APIs delegate to `src`; legacy order creation remains temporarily. |
| `fLineStrategy*.py` | `strategy.line` | Public profiles delegate to `src`. |
| OANDA query/execution | `adapters.oanda` | New applications use the shared `OandaClient`. |
| Discord notices | `adapters.notifications.DiscordNotifier` | `send_notice.line_send` retains legacy argument and duplicate semantics, then delegates. |
| Trade history CSV | `adapters.repositories.CsvTradeHistoryRepository` | `classPosition.order_information` accepts an optional injected repository. |
| Position slots and synchronization | `application.services.PositionPortfolioService` | Root position-control remains a legacy facade until callers migrate. |

## Live Entrypoint

`ogami_oanda.entrypoints.live` is the new composition root. It creates one OANDA client for market data, execution, and query adapters; then composes notification, history, position, portfolio, analysis, and planning services.

Run a single cycle with explicit configuration:

```sh
.venv/bin/python -m ogami_oanda.entrypoints.live --settings config/settings.yaml --dry-run
```

`--dry-run` performs analysis and registers watching positions but does not submit broker orders. Pending orders are never cancelled by default; pass `--cancel-pending-on-start` only when that action is intended. The initial entrypoint uses an injected candidate builder and defaults to no candidates, so wiring a production strategy is an explicit composition decision rather than an implicit root-module dependency.

## Legacy Boundaries

- `classPosition.py` accepts optional `oanda_factory` and `notifier` dependencies. Existing two-argument construction remains supported.
- `classPosition.py` also accepts an optional `history_repository`; without it, its existing `history_folder_path/history.csv` behavior remains unchanged.
- `classPositionControl.py` remains the legacy `ActiveOrderQuery` implementation until callers migrate to `application.services.Portfolio`.
- `main_exe.py` retains its existing startup cancellation behavior during the migration. New deployments should use `entrypoints.live`, where cancellation is opt-in.
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