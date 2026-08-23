# Differential verification

## Purpose

The differential suite compares the immutable baseline commit
`eff331c2367570dcb8bc35a323a382e8255eda7b` with the current `src/ogami_oanda`
implementation. It is offline and must never submit an OANDA order or deliver a
Discord notification.

A parity result means that the captured behavior matches the baseline, except
for reviewed entries in `tests/differential/intentional_deltas.json`. It does
not prove that the behavior is correct for the current OANDA API. API wire
compliance and practice acceptance are separate gates.

## Fixed baseline

The accepted identity is:

- Commit: `eff331c2367570dcb8bc35a323a382e8255eda7b`
- Tree: `7dc341e37b663e7f206736abfe001e81fe74dd6a`

The harness verifies the full commit and tree IDs, required files, and required
legacy symbol snippets before replay. A detached temporary worktree is checked
for the expected HEAD and a clean status before and after every scenario. The
baseline checkout and production code are never instrumented or modified.

## Two gates

Run the fast current-versus-golden gate during normal development:

```sh
.venv/bin/python -m pytest -q tests/differential/test_harness_contract.py
.venv/bin/python tests/differential/cli.py compare-current --all
.venv/bin/python -m pytest -q tests/differential/test_current_against_golden.py
```

Run the explicit provenance gate when the runner, scenario schema, golden
artifacts, or allowlist changes:

```sh
.venv/bin/python tests/differential/cli.py verify-baseline \
  --all \
  --legacy-ref eff331c2367570dcb8bc35a323a382e8255eda7b

.venv/bin/python -m pytest -q \
  tests/differential/test_baseline_reproducibility.py \
  --run-baseline-replay \
  -m baseline_replay
```

The default offline suite does not create a worktree because baseline tests are
skipped unless `--run-baseline-replay` is supplied.

## Trace contract

Scenarios are JSON files under `tests/differential/scenarios/`. Shared analysis
frame references are materialized into deterministic raw OANDA candle responses
before execution. Legacy and current code independently map and prepare those
responses; the harness never shares prepared indicators. Position scenarios
materialize an explicit 15-slot input. Live scenarios carry an ordered tick
sequence whose `price_response` is the raw OANDA pricing envelope. Current code
decodes it with `map_price_response`; the legacy fake independently reproduces
the pinned `NowPrice_exe` pair rounding. Each quoted tick contains exactly one
bid and ask string plus OANDA status, and one scheduler quote call consumes that
response once. A market-closed tick correctly consumes no quote.

Position scenarios may carry one ordered `broker_steps` list. Every step names
the expected action and owns the raw response used by both adapters, for
example:

```json
{"action": "order", "response": {"state": "PENDING", "order_id": "order-1"}}
```

An action mismatch, response underflow, or leftover applicable step fails the
runner. The `runner` field is permitted only when an already reviewed behavioral
delta makes the call sequences inherently different; those actions remain
visible in `broker_actions` rather than being made falsely equal.

Trace schema `1.1.0` keeps source-specific projections. The common code only
serializes built-in values and defines the trace shape; it does not compute
legacy or current strategy results. The six order payload scenarios construct a
current `OrderIntent` and `OrderContext`, then call the production
`OrderPlanner`.

The legacy live differential driver executes the real scheduler methods
`exe_manage()`, `mode1()`, and `mode2()`. Analysis, Position, candle, broker,
and notification collaborators are deterministic test doubles. This proves
scheduler decision and call-order parity, not full legacy live end-to-end
parity. Position-service scenarios separately exercise lifecycle behavior;
OANDA API wire compliance and credentialed practice acceptance remain separate
gates.

Canonical traces preserve:

- complete prepared frame rows and indicator columns;
- every ordered peak, line, raw candidate, selected candidate, and inherited
  strategy/profile setting;
- source-specific enriched candidates with session, path, sizing, and final
  plan fields;
- typed intents, semantic plans, adapter plans, adapter metadata-loss maps,
  legacy payloads, and current OANDA wire payloads;
- tick-by-tick position state, commands, events, history columns and rows,
  notifications, and analytics;
- live quote, sync, analysis, registration, and post-analysis sync ordering.

Mapping keys are ordered, list order is preserved, NaN becomes `null`, datetime
values are converted to JST ISO strings, and only semantic broker identifier
fields are mapped to first-seen stable IDs. Price fields are rounded to the
pair's price precision. Pips coordinates and distances, including line
`median`, `median_p`, and `range_min`/`range_max`, plus units, priorities, and
boundary seconds are not rounded away.

Both runners install a process-level `requests` and socket blocker. Baseline
replay also rejects any `ogami_oanda` import, scans loaded module origins for
the current workspace `src`, and verifies detached-worktree HEAD and cleanliness
on both successful and exceptional exits.

## Adding a scenario

1. Add one JSON file with a unique `scenario_id`.
2. Supply raw or materializable input only. Do not put expected outputs in the
   scenario.
3. Add the smallest legacy/current driver case that calls the behavior owner.
4. Run the scenario directly against the baseline before updating golden:

   ```sh
   .venv/bin/python tests/differential/cli.py capture-legacy \
     --scenario-id <scenario-id> \
     --out build/differential/probe
   ```

5. Run the fast runner contract and inspect every mismatch.
6. Add an intentional delta only after observing and reviewing the exact
   baseline/current values.
7. Regenerate golden and run both gates.

## Intentional deltas

Every allowlist entry must include a unique ID, one scenario, one absolute JSON
pointer, exact baseline and current values, a technical reason, a document
reference, and an expiry date. Added and removed values use an exact
`{"$missing": true}` matcher. A large scalar or reviewed subtree may use an
exact canonical JSON SHA-256 matcher on both sides. Raw list or mapping
containers, wildcards, expired entries, stale entries, and unexpected
differences are rejected. The full gate also requires every selected allowlist
entry to apply exactly once. An allowlisted first difference never hides a later
unexpected difference.

### Analysis pipeline deltas

All three pairs form the reviewed H1 lines from the same source prices, count,
median, and strength, but one line per pair retains a different pips-coordinate
cluster range. The six exact `range_min`/`range_max` leaves remain explicit.

The EUR/USD selected order also exercises the H1 path-shortening rule. The
legacy flat plan and current typed pipeline expose different source object
shapes, original-price ownership, and metadata placement. Exact subtree hashes
fix the complete enriched candidate, typed intent, semantic plan, adapter plan,
and adapter metadata-loss map. Any added, removed, or changed strategy,
session, path, sizing, intent, or plan field invalidates those hashes.

The 21:55 multi-selection EUR/USD case selects the same nine ordered breakout
candidates in both analyses. Legacy finalization removes three near-line
duplicates and emits six final plans; current analysis emits all nine and leaves
portfolio admission/deduplication to its downstream service. Exact ordered
subtree hashes cover only the finalization-derived candidate/intent/plan/payload
surfaces. Raw frames, indicators, peaks, lines, all nine selected candidates,
and recommendation order remain leaf-compared outside the allowlist.

### OANDA wire contract deltas

Current LIMIT and STOP requests include top-level `timeInForce=GTC`. Current
MARKET requests use `timeInForce=FOK` and omit top-level `price`. The immutable
legacy projection omitted top-level `timeInForce` and retained `price` for
MARKET. These are API-compliance changes and must not be reverted merely to make
legacy parity exact.

### Broker reconciliation deltas

Legacy marks an order cancelled after four consecutive missing detail queries.
Current code retains the pending state until authoritative broker
reconciliation resolves the mutation. This prevents an assumed terminal state
from enabling an unsafe resubmission.

### Close reporting deltas

The typed current history projection has a few representation differences from
the mutable legacy object, including numeric text formatting, timestamp
separators, memo ownership, and concise notification text. History column order,
record values, event one-time behavior, and analytics remain directly compared.

### Portfolio acceptance deltas

Legacy partially accepts an overfull priority-tier batch. Current code rejects
the complete overfull tier atomically so a strategy batch cannot be only partly
executed.

### Live orchestration deltas

After a zero-candidate analysis, the current application still calls
`register_plans([])` as an explicit no-op orchestration step. Legacy skips that
call. The candidate-present scenario is not allowlisted and compares
`quote -> sync -> analysis -> register -> sync` strictly, including plan,
accepted, and rejected counts.

## Updating golden

Golden updates are never implicit. The command requires the exact SHA twice:

```sh
.venv/bin/python tests/differential/cli.py update-golden \
  --all \
  --legacy-ref eff331c2367570dcb8bc35a323a382e8255eda7b \
  --confirm-baseline-sha eff331c2367570dcb8bc35a323a382e8255eda7b
```

The manifest records baseline commit/tree, trace schema version, Python and
numeric-library versions, SHA-256 for every runner file, each raw scenario file,
the fully materialized input, and each trace. The fast gate verifies all these
hashes, exact dependency versions, schemas, and unknown keys before comparing
current behavior. Checked-in updates require `--all`; traces and the manifest
are built in a staging directory and replace the golden directory only after
the complete capture succeeds.

Tests prove process-local rollback for both capture failure and replacement
rename failure: the previous golden directory remains byte-identical, and the
temporary `.replacement` and `.backup` directories are removed. This is not a
claim of crash consistency across an operating-system or power failure.

Legacy time is frozen before live construction. The baseline replay gate
captures every scenario twice in fresh subprocesses and requires identical
canonical SHA-256 values.

## Failure artifacts

Unexpected differences are written to
`build/differential/<scenario-id>/`:

- `legacy.trace.json`
- `current.trace.json`
- `diff.json`
- `legacy.log.txt` when a baseline run was involved

`diff.json` contains the first unexpected JSON pointer, both values, stale
allowlist IDs, and canonical trace hashes. Start at that pointer, then inspect
the surrounding events in both traces. Do not update golden or broaden an
allowlist before identifying which implementation owns the difference.

## Final local acceptance

```sh
.venv/bin/python -m pytest -q tests/differential/test_harness_contract.py
.venv/bin/python tests/differential/cli.py compare-current --all
.venv/bin/python tests/differential/cli.py verify-baseline \
  --all --legacy-ref eff331c2367570dcb8bc35a323a382e8255eda7b
.venv/bin/python -m pytest -q \
  tests/differential/test_baseline_reproducibility.py \
  --run-baseline-replay -m baseline_replay
.venv/bin/python -m pytest -q -m 'not integration and not baseline_replay'
.venv/bin/python -m ruff check src tests
.venv/bin/python -m compileall -q src tests
```

### Verified 2026-08-24

The completed local run used 41 scenarios: 4 analysis, 6 order payload, 21
Position lifecycle, and 10 live scheduler scenarios. Results:

- harness contract: 36 passed;
- current-versus-golden CLI: all 41 scenarios passed, with every applicable
  allowlist entry consumed exactly once;
- fast parity pytest: 1 passed;
- exact baseline CLI: all 41 scenario hashes matched golden;
- baseline replay/determinism pytest: 4 passed, 1 deselected;
- repository offline suite: 440 passed, 20 deselected;
- Ruff: all checks passed;
- `compileall`: exit 0.
