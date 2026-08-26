# Matcha Python + YAML Strategy Plugin Implementation Plan

> Execute task-by-task with test-driven development, task review, and final branch verification.

**Goal:** Allow `ogamiOanda` live trading strategies to be selected as trusted Python + YAML pairs, while preserving the existing line strategy as the unchanged default, and natively port the current working-tree versions of BFScalping's `matcha_oanda.py` and `matcha_param2019_oanda.yaml`.

**Architecture:** A package-local plugin loader validates and imports a Python strategy factory, parses a YAML mapping, and returns a versioned `TradingStrategy`. A matcha-specific application runner supplies quotes and cached M1 candles, translates strategy decisions into existing order plans plus source-scoped portfolio commands, and persists strategy identity/state through the existing checkpoint boundary. Broker access remains behind existing application ports and adapters.

**Tech Stack:** Python 3.12, pytest, dataclasses/protocols, importlib, PyYAML, NumPy/Pandas, existing OANDA adapters and portfolio services.

**Behavioral source:** Current dirty working-tree files `/Users/koji/git/BFScalping/oanda/strategy/matcha_oanda.py` and `/Users/koji/git/BFScalping/oanda/strategy/matcha_param2019_oanda.yaml`. They are reference inputs only and must not be modified or imported at runtime.

## Global Constraints

- Work only in `ogamiOanda`; preserve BFScalping's dirty working tree and never copy its webhook values.
- The package strategy directory is `src/ogami_oanda/strategy`.
- The built-in line strategy remains byte-for-behavior the default when no plugin arguments are supplied.
- Plugin CLI is exactly `--strategy-py PATH --strategy-yaml PATH`; both or neither. Resolve from cwd, then reject either resolved path outside package `ogami_oanda/strategy`.
- Plugins are trusted local Python and must expose `STRATEGY_API_VERSION = 1` and `create_strategy(config) -> TradingStrategy`.
- Strategy code may import only strategy/domain layers; no BF `libs`, application, adapter, infrastructure, network, filesystem, or broker dependency.
- Initial matcha supports only `USD_JPY`, `AutoLot: false`, `Cancel: false`, `MaxPos: 1`, `tp_sl_amount_mode: true`, `tp_sl_close_intent_suppress: true`, `close_position: false`, and `timescale: 60`; reject unsupported values at startup.
- Keep current YAML tunables effective, including sigma/CTP/BreakOut/LotSize. Leave only this notification marker in the destination YAML: `# TODO(notification-integration): strategy固有通知は共通notifications設定との統合時に追加する。`
- BreakOut MARKET orders receive the same fixed-amount TP/SL protection as LIMIT entries.
- Preserve existing spread/weekend/tradeable gates. Stale or unknown quotes suppress entry; max-latency breach generates emergency source-scoped cancel/close.
- Evaluate risk each quote tick with cached M1 candles; normal LIMIT entry at most once per new completed M1 candle. Fetch 1000 newest-first M1 candles and reverse only within matcha math.
- Command precedence is emergency cancel+close, flatten cleanup, max-exposure correction, breakout reverse/add, normal entry. Run commands before intents; rejection or UNKNOWN suppresses new intents.
- Portfolio command types are `CANCEL_PENDING`, `REDUCE_EXPOSURE`, and `CLOSE_ALL`, source-scoped. Partial reductions are oldest `filled_at`, then slot, with final trade partially closed.
- Every new intent goes through existing `OrderPlanner` and `register_plans`.
- Dry-run may report commands/plans but performs no broker mutation and no checkpoint write.
- `minutes_to_expire: 7` feeds the existing order timeout. `sfdCheck` is diagnostic-only.
- Checkpoint schema becomes v2 and stores `strategy_id` plus JSON strategy state. Active mismatches are quarantined; empty checkpoints may adopt. Schema v1 is the built-in line identity and may migrate to plugin only when empty.
- Practice actual-order strategy acceptance is practice-only, uses broker-minimum units, at most two generated orders, and succeeds only after final pending/open deltas return to zero. Cleanup cancels pending orders and closes fills. Never run this against live accounts.
- Out of v1: strategy notifications, hot reload, AutoLot, Cancel true, MaxPos other than 1, non-USD_JPY matcha, backtest integration, conversion of the built-in line strategy, BF logging/graph/API/cryptowatch compatibility, and root legacy CLI changes.

### Task 1: Add Strategy Plugin Contracts, Loader, and Quote Timestamp

**Files:**
- Create focused modules under `src/ogami_oanda/strategy` for contracts and loading.
- Modify `src/ogami_oanda/application/ports/market_data.py`.
- Modify OANDA market-data mapper/adapter files.
- Add plugin loader, dependency-rule, and quote timestamp tests.

**Steps:**
- Write failing tests for the API version/factory contract, YAML mapping validation, pair validation, both path containment rules, and source timestamp parsing.
- Define broker-agnostic strategy inputs/outputs/state JSON types and the `TradingStrategy` protocol.
- Implement deterministic `strategy_id` from resolved Python/YAML content hashes.
- Implement a loader that validates before constructing a strategy and produces actionable startup errors.
- Extend `MarketQuote` with optional timezone-aware `source_time`; parse OANDA price `time` without breaking callers that omit it.

**Completion:** Focused contract tests pass and architecture dependency tests remain green.

### Task 2: Port Matcha Configuration, Math, Decisions, and State

**Files:**
- Add `src/ogami_oanda/strategy/matcha_oanda.py`.
- Add `src/ogami_oanda/strategy/matcha_param2019_oanda.yaml` without secrets.
- Add fixed BF-derived fixtures and matcha unit/characterization tests.

**Steps:**
- Capture hand-checked fixed outputs from the current BF files before production implementation; never import BF at runtime.
- Write failing tests for startup rejection of every unsupported route and acceptance of supported tunables.
- Port price calculation, lot formulas, flat LIMIT, breakout MARKET, same-direction add, opposite-direction reduce/reverse, maximum-position correction, cooldown, freshness, and restart state behavior.
- Ensure MARKET and LIMIT intents both have fixed-amount TP/SL protection and `minutes_to_expire: 7` is represented.
- Keep state JSON serializable, including last candle, previous net units, cooldown, and the latest 100 quote-latency samples.

**Completion:** All matcha branches and fixed characterization fixtures pass without BF imports.

### Task 3: Integrate Matcha Runtime, Portfolio Commands, and Checkpoint v2

**Files:**
- Add a custom-strategy application service/runner.
- Modify portfolio/position services and broker mutation recovery as needed.
- Modify JSON position state repository/checkpoint models.
- Modify `src/ogami_oanda/entrypoints/live.py` without changing the no-plugin path.
- Add runtime, command, partial-close, recovery, checkpoint, and live default-regression tests.

**Steps:**
- Write failing tests for per-tick risk, once-per-M1 normal entry, 1000-candle order handling, command precedence, command-before-intent suppression, and dry-run immutability.
- Translate matcha decisions into source-scoped cancel/reduce/close commands and existing planner/register paths.
- Make deterministic partial close and UNKNOWN reconciliation unit-aware; persist enough journal units to recover partial reductions.
- Implement checkpoint v2 identity/state migration and quarantine rules.
- Wire dynamic strategy scheduling while leaving the existing line schedule/service untouched when no plugin is supplied.

**Completion:** Focused integration tests pass and existing live/position recovery contracts remain green.

### Task 4: Add CLI, Packaging, and Operator Documentation

**Files:**
- Modify live CLI and `pyproject.toml` package data.
- Update relevant architecture/operator docs and settings examples only where needed.
- Add CLI, wheel/package-data, offline-smoke, and documentation-facing behavior tests.

**Steps:**
- Write failing CLI tests for both-or-neither, outside-package rejection, plugin loading, and unchanged default behavior.
- Package the YAML with the installed distribution.
- Document trusted-plugin boundaries, invocation, supported matcha subset, state mismatch quarantine, dry-run behavior, and secret rotation warning without repeating any secret.
- Verify built-in line offline smoke and matcha dry-run smoke.

**Completion:** Installed-package lookup works and all CLI/default regressions pass.

### Task 5: Extend Practice Acceptance for Strategy Mode

**Files:**
- Modify practice acceptance entrypoint/service with the smallest reusable additions.
- Add practice strategy acceptance tests using complete broker fakes.

**Steps:**
- Write failing tests for strict practice/account confirmation gates, generated-intent price/direction/TP/SL preservation, broker-minimum unit clamping, two-order cap, UNKNOWN discovery, pending/fill cleanup, and zero final deltas.
- Add optional Python+YAML strategy mode while preserving existing acceptance behavior without those options.
- Reuse generated strategy intents but clone units to the configured broker minimum.
- Keep actual broker execution behind all existing destructive acceptance confirmations.

**Completion:** Fake-backed strategy acceptance coverage passes; read-only practice verification remains available before any external mutation.

### Task 6: Run Full Verification and Review

**Files:**
- No feature expansion; tests/docs fixes only when verification exposes defects.

**Steps:**
- Run all focused suites, full offline pytest, Ruff, compileall, architecture rules, differential verification, built-in line offline smoke, matcha dry-run smoke, and practice read-only checks.
- Obtain task reviews and a whole-branch code review; fix all critical/important findings and reverify.
- If practice credentials and explicit safety confirmation are available, run minimum-unit actual-order strategy acceptance and independently query final pending/open state. Otherwise report this external acceptance as the sole remaining gated step.

**Completion:** Every local/offline gate is fresh and green, review is clean, and external acceptance is either evidenced or explicitly identified as awaiting its security-sensitive gate.
