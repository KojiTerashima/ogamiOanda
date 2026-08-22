# Architecture migration

## Layer ownership

The production package is split by responsibility:

| Layer | Owns | May depend on |
| --- | --- | --- |
| `domain` | immutable order/position models, currency-pair math, candle/peak/line calculations | `domain` only |
| `strategy` | candidate selection and order decisions: direction, market/limit/stop, target, risk-sized units, TP, SL, timeout, pair profiles, and lifecycle policies | `strategy`, `domain` |
| `application` | ports and use-case orchestration for analysis, planning, portfolio lifecycle, reporting, and scheduling | `application`, `strategy`, `domain` |
| `adapters` | OANDA endpoint definitions/mapping, Discord HTTP, CSV persistence, legacy dictionary conversion | application ports and domain types |
| `infrastructure` | YAML/token configuration, explicit JST clock, fixed-interval polling loop | infrastructure and application configuration types |
| `entrypoints` | dependency construction only | all production layers |
| `tests` | fakes, characterization oracles, contracts, architecture and acceptance matrices | production public APIs; production never imports tests |

Dependency direction is enforced by
`tests/architecture/test_dependency_rules.py`. In particular:

- `src` cannot import root legacy modules or the test layer.
- application cannot import adapters or infrastructure.
- strategy and domain cannot import adapters, infrastructure, OANDA, requests,
  or tokens.
- `oandapyV20` is confined to `adapters/oanda`.
- `requests` is confined to `adapters/notifications`.
- wall-clock and loop sleep calls are confined to `infrastructure/runtime`.

## Data and decision flow

One live tick follows this flow:

1. `MarketDataPort.current_quote()` obtains one typed bid/ask/mid quote.
2. The schedule decides market-closed, update-only, lifecycle-sync, and
   analysis behavior.
3. The OANDA adapter maps candles to the canonical newest-first
   `time_jp/open/close/high/low` contract.
4. domain analysis adds indicators, peaks, and line classes.
5. `LineCandidateBuilder` applies the pair profile and returns ordered strategy
   decisions, including risk-sized units, protection values, timeout, reasons,
   and the legacy-compatible line/session metadata used downstream.
6. `MarketAnalysisService` converts selected candidates to immutable
   `OrderIntent` values; `OrderPlanner` derives prices and a broker-neutral
   `BrokerOrderRequest`.
7. `PositionPortfolioService` applies deduplication and slot policy, while
   `PositionService` evaluates watching, timeout, stop-loss, linkage, hedge, and
   close-reporting policies through ports.
8. Only an execution adapter translates the broker-neutral request into an
   OANDA payload or mutates broker state.

The application and strategy layers therefore do not know OANDA endpoint
classes, account tokens, Discord, CSV paths, or the polling implementation.

## Live schedule

`ogami_oanda.entrypoints.live.LiveApplication` preserves the historical
scheduler:

- Sunday: return before requesting a quote.
- Saturday from 04:00 and Monday through 07:59: update-only after
  initialization.
- spread above the pair-specific limit: update-only after initialization.
- first execution: the historical runner analyzes immediately after its single
  quote even when that first tick is in an update-only or wide-spread window;
  it does not run a separate lifecycle sync in that tick.
- later analysis: minute divisible by five, second in `[6, 30)`, and more than
  60 seconds since the previous analysis.
- later scheduled analysis first performs the historical mode-1 lifecycle sync,
  then analyzes/registers; an even-second tick performs the separate mode-2
  sync afterward as well. Non-analysis even seconds sync once, and update-only
  windows sync every tick.
- `run_forever`: infrastructure-owned one-second fixed-deadline polling; finite
  runs are injectable for tests and unbounded runs do not accumulate results.

The quote is requested once per tick and reused for spread, lifecycle, and
analysis decisions.

## Composition and command line

Install the package in editable mode:

```sh
.venv/bin/python -m pip install -e .
```

Run one cycle:

```sh
.venv/bin/ogami-oanda-live \
  --config config/settings.yaml \
  --account primary \
  --pair USD_JPY \
  --dry-run \
  --once
```

`--settings` is an alias for `--config`. `--once` prints planned names,
accepted names, and rejection reasons. `--dry-run` permits reads and decision
generation but performs no submit, cancel, close, protection amendment, or
startup cancellation.

For a dependency-free packaging smoke that neither loads a config nor creates
an OANDA/Discord/CSV adapter:

```sh
.venv/bin/ogami-oanda-live \
  --pair USD_JPY \
  --offline-smoke \
  --dry-run \
  --once
```

`--offline-smoke` requires both `--dry-run` and `--once`; it verifies the
installed console entrypoint and one scheduling tick. A regular dry-run still
uses read-only market and account queries so it can produce real decisions.

New CLI startup cancellation is opt-in with
`--cancel-pending-on-start`. The historical `main_exe.py` facade opts in for
compatibility, except during dry-run. EUR/USD and AUD/USD root launchers pass a
pair argument to the same builder; they do not mutate a global currency pair.

The composition creates one `OandaClient` per selected account and shares it
with market-data, execution, and query adapters.

## Root compatibility boundary

The production root facades are:

- `fLineAnalysis.MainAnalysis`
- `fLineAnalysis.LineOrderCoordinator`
- `fAnalysis_order_Main.wrap_all_analysis`
- `classPositionControl.position_control`
- `main_exe.py`, `main_exe_euro.py`, and `main_exe_aud.py`

`classPositionControl.position_control` now uses the `src` portfolio by default.
It maintains legacy method returns and projects slots into
`classPosition.managed_position_view`. The mutable
`classPosition.order_information` and `classOanda.Oanda` implementations remain
only for characterized or explicitly excluded root tools; they are not reached
by the new live call graph. See `docs/migration-map.md` for their removal gates.

## Offline acceptance

Run the complete gate:

```sh
.venv/bin/python -m pytest -q -m "not integration"
.venv/bin/python -m ruff check src tests
.venv/bin/python -m compileall -q src tests
.venv/bin/ogami-oanda-live --help
.venv/bin/ogami-oanda-live --offline-smoke --dry-run --once
```

The offline matrix covers:

- USD/JPY, EUR/USD, and AUD/USD M5/H1/M30/S5 frame schemas.
- ordered lines, raw/selected candidates, recommendation reasons,
  `OrderIntent`, `OrderPlan`, and OANDA payloads.
- 15 slots, priority tiers, deduplication, watching, timeout, SL changes,
  linkage/hedge, close history/analytics, and root view projection.
- three-pair live dry-run, weekend/update-only/spread boundaries, five-minute
  analysis, two-second sync, one-second polling, startup cancellation, legacy
  launchers, and CLI output.
- static dependency direction and external-I/O confinement.

OANDA practice read-only checks require credentials and must use the
`integration` marker. Practice orders and real Discord delivery are not part of
the offline acceptance gate.
