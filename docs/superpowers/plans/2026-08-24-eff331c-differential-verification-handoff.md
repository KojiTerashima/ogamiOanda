# eff331c Differential Verification Remaining Work Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Use `superpowers:test-driven-development` for each behavioral fix and `superpowers:verification-before-completion` before claiming completion. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Finish the remaining work in the original `plan.md` for the `eff331c` differential verification harness without repeating completed work or mixing unrelated workspace changes.

**Architecture:** The immutable baseline commit runs in a detached worktree and isolated subprocess. Baseline and current runners consume deterministic scenario inputs and emit canonical JSON traces. Normal development compares current output with checked-in golden traces; an explicit provenance gate replays the exact baseline commit. Intentional differences use scenario- and JSON-pointer-scoped exact values or exact normalized subtree hashes.

**Tech Stack:** Python 3.12.5, pytest, pandas, NumPy, Ruff, git detached worktrees.

**Spec:** Original conversation attachment `plan.md`, titled `Plan: eff331c差分検証基盤`. Operational companion: `docs/differential-verification.md`.

## Global Constraints

- Baseline commit is exactly `eff331c2367570dcb8bc35a323a382e8255eda7b`.
- Baseline tree is exactly `7dc341e37b663e7f206736abfe001e81fe74dd6a`.
- Keep all comparison instrumentation under `tests/differential`; do not modify production `src`, root legacy implementation, or the baseline worktree for parity instrumentation.
- All differential execution is offline and must issue zero real OANDA/Discord/socket/requests calls.
- Preserve list, candidate, reason, command, CSV-column, and event ordering.
- Normalize broker-issued IDs only. Keep names, pips, ranges, spread, units, priorities, and boundary seconds observable.
- Do not add a GitHub Actions workflow in this task.
- Do not update golden artifacts until all runner/schema/allowlist changes are final and focused tests are green.
- Do not use `git add -A`, `git reset`, checkout-based revert, or stash. The working tree contains a large uncommitted differential implementation and untracked `.vscode/` content.
- Stage only explicit differential/docs paths after all gates pass.

---

## Handoff Snapshot

**Recorded:** 2026-08-24

- Branch: `feat/live-order-completion`
- HEAD: `d6b6923f2eb389b83c314f6e8c5ee3a8dd51b16f`
- Index: clean at handoff audit
- Working tree: intentionally dirty; the differential completion is mostly uncommitted
- Scenario count: 40
  - `analysis_order`: 3
  - `order_payload`: 6
  - `position_lifecycle`: 21
  - `live_schedule`: 10
- Golden directory already contains 40 traces, but several live traces and the manifest are stale relative to current runner code.

### Latest Verified Results

Green:

```text
.venv/bin/python -m pytest -q tests/differential/test_harness_contract.py
27 passed
```

```text
Full 40-scenario fresh-subprocess determinism test
1 passed in about 90 seconds
```

```text
Baseline identity/contract test
1 passed
```

```text
.venv/bin/python -m ruff check src tests
All checks passed
```

```text
.venv/bin/python -m compileall -q src tests
exit 0
```

Red:

```text
.venv/bin/python -m pytest -q tests/differential/test_current_against_golden.py
FAIL: manifest runner_sha256 does not match runner files
```

The last full offline run reached `429 passed, 1 failed, 19 deselected`; the sole failure was the same stale manifest check.

A direct baseline/current comparison currently exposes one live-spread defect at two tick pointers:

```text
/events/0/quote/spread 0.012 => 0.012000000000000455
/events/1/quote/spread 0.011 => 0.01099999999999568
```

Do not allowlist or globally normalize this difference. Fix the live quote input/mapping contract first.

---

## Completed Work: Do Not Repeat

The following implementation exists in the current working tree and has focused coverage:

- Exact baseline commit/tree/file/symbol checks.
- Detached worktree creation, HEAD/clean checks, cleanup, timeout outcome, and structured subprocess errors.
- Legacy subprocess import blocker preventing current `ogami_oanda` imports.
- Requests/socket network blockers and current-runner offline guard.
- Canonical trace schema version `1.1.0`.
- Raw OANDA candle response generation and separate baseline/current mapping paths.
- Full prepared-frame, indicator, peak, four-line-class, raw/selected/enriched candidate, strategy/profile, intent, semantic plan, adapter plan, payload, and metadata-loss trace surfaces.
- Current order scenarios route through production `OrderPlanner` and OANDA mapper.
- Legacy live scenarios invoke real `main_exe.main.exe_manage()`, `mode1()`, and `mode2()`; analysis/position/candle/OANDA dependencies are leaf fakes. Treat this as scheduler parity, not full legacy live end-to-end parity.
- Position coverage for watching, timeout, LC rules, candle LC, priority tiers, overflow, broker outcomes, linkage, hedge no-op, close reporting, restore, and source-aware deduplication.
- Strict all-leaf comparison including added/deleted keys and list elements.
- Exact `$missing` and SHA-256 subtree matchers; wildcard/container allowlists are rejected.
- Allowlist expiry injection, orphan rejection, unknown-key rejection, stale detection, and exactly-once aggregate validation.
- Source-specific analysis projection and regression tests for inherited strategy/profile fields, `effective_tp_pips`, `order_permission`, and adapter metadata loss.
- Manifest schema/hash/version/envelope/canonical-byte validation.
- Full-set-only staged golden update with rollback attempt.
- Operational documentation in `docs/differential-verification.md` and parity/API distinction in migration docs.
- Scenario/manifest provenance includes raw scenario and materialized input hashes.

Do not simplify these surfaces back to candidate counts, legacy pre-finalization arithmetic, scripted `mode1`/`mode2`, container-level allowlists, or broad float rounding.

---

## Remaining Work by Original Plan Step

| Original Step | State | Remaining Work |
| --- | --- | --- |
| 1–6 | Mostly complete | Add remaining failure-path tests and preserve current strict contracts. |
| 7 | Partial | Final golden/manifest regeneration is blocked by live spread and remaining raw-input work. Add stronger failure-path coverage for staged replacement. |
| 8 | Complete in structure | Re-run default and explicit gates after final golden update. |
| 9 | Partial | Add a real-strategy multiple-selected/final-plan analysis case; record bootstrap oracle relationship. |
| 10 | Broadly complete | Prefer raw Broker response sequences over case-specific state construction where feasible. |
| 11 | Partial | Replace interpreted live quote input with raw OANDA pricing response and route current through `map_price_response`; clarify scheduler-only legacy scope. |
| 12 | Partial | Correct documentation wording after raw quote/Broker work and record final commands/results. |
| 13 | Red | Run all acceptance gates only after Tasks 1–5 and final golden update. |

---

### Task 1: Fix Live Raw Quote and Spread Contract

**Files:**
- Modify: `tests/differential/test_harness_contract.py`
- Modify: `tests/differential/scenario.py`
- Modify: `tests/differential/current_runner.py`
- Modify: `tests/differential/legacy_runner.py`
- Likely modify: `tests/differential/frame_factory.py` or create `tests/differential/market_input.py`
- Test scenario: `tests/differential/scenarios/live-spread-boundary-usd-jpy.json`

**Interfaces:**
- Consumes: materialized `live.ticks`, `ogami_oanda.adapters.oanda.mappers.map_price_response()`, baseline pair rounding.
- Produces: one shared raw OANDA pricing response per tick and identical semantic `bid/ask/mid/spread/tradeable` traces.

- [x] **Step 1: Add the failing spread regression**

```python
@pytest.mark.unit
def test_live_spread_boundary_trace_uses_pair_precision():
    scenario = next(
        item
        for item in load_all_scenarios()
        if item.scenario_id == "live-spread-boundary-usd-jpy"
    )

    events = run_current_scenario(scenario).trace["events"]

    assert events[0]["quote"]["spread"] == 0.012
    assert events[1]["quote"]["spread"] == 0.011
```

- [x] **Step 2: Run the test and verify RED**

```sh
.venv/bin/python -m pytest -q \
  tests/differential/test_harness_contract.py \
  -k live_spread_boundary_trace_uses_pair_precision
```

Expected current failure values:

```text
0.012000000000000455
0.01099999999999568
```

- [x] **Step 3: Materialize a raw OANDA pricing response**

Use this input shape for each live tick:

```python
{
    "prices": [
        {
            "bids": [{"price": "150.000"}],
            "asks": [{"price": "150.012"}],
            "status": "tradeable",
        }
    ]
}
```

Current must call `map_price_response(pair, response)`. Legacy must decode the same raw response through baseline-owned pair rounding or an equivalent leaf fake that reproduces `NowPrice_exe` semantics. Do not share current production mapper with the legacy runner.

- [x] **Step 4: Require one raw response consumed per tick**

Add assertions for:

```python
assert event["quote_count"] == 1
assert event["quote"] == {
    "bid": 150.0,
    "ask": 150.012,
    "mid": 150.006,
    "spread": 0.012,
    "tradeable": True,
}
```

- [x] **Step 5: Run focused baseline/current comparison**

```sh
.venv/bin/python - <<'PY'
from pathlib import Path
from tests.differential.compare import compare_traces, load_allowlist
from tests.differential.current_runner import run_current_scenario
from tests.differential.orchestrator import capture_legacy_trace
from tests.differential.scenario import load_all_scenarios
from tests.differential.trace import ensure_trace_envelope

scenario = next(
    item for item in load_all_scenarios()
    if item.scenario_id == "live-spread-boundary-usd-jpy"
)
legacy = capture_legacy_trace(repo_root=Path.cwd(), scenario=scenario).trace
current = ensure_trace_envelope(
    run_current_scenario(scenario).trace,
    scenario_id=scenario.scenario_id,
    runner="current",
)
result = compare_traces(
    scenario_id=scenario.scenario_id,
    baseline_trace=legacy,
    current_trace=current,
    allowlist_entries=load_allowlist(),
)
assert result.matched, result.mismatches
PY
```

**Completion criterion:** Both spread pointers disappear without normalizer or allowlist changes, and all 10 live scenarios still execute.

---

### Task 2: Unify Raw Broker Query and Command Response Sequences

**Files:**
- Modify: `tests/differential/scenario.py`
- Modify: `tests/differential/scripted_broker.py`
- Modify: `tests/differential/legacy_runner.py`
- Modify: `tests/differential/current_runner.py`
- Modify: representative `tests/differential/scenarios/position-*.json`
- Test: `tests/differential/test_harness_contract.py`

**Interfaces:**
- Consumes: ordered raw Broker query/command response records in scenario input.
- Produces: baseline/current adapters that consume each response exactly once and fail on leftovers, underflow, or action mismatch.

- [x] **Step 1: Add a failing shared-response contract**

Define scenario-owned ordered steps such as:

```json
{
  "broker_steps": [
    {"action": "submit", "response": {"state": "PENDING", "order_id": "1001"}},
    {"action": "order", "response": {"state": "PENDING", "order_id": "1001"}},
    {"action": "cancel_order", "response": {"accepted": true, "order_id": "1001"}}
  ]
}
```

Test that both runners reject a wrong action, missing step, or unconsumed step.

- [x] **Step 2: Extend `ScriptedBroker` to consume the raw sequence**

Keep broker-neutral parsing in test code. Current production services still receive typed port results. Record every query and command in trace order.

- [x] **Step 3: Extend `_LegacyFakeOanda` to consume the same sequence**

Translate each shared raw response into the baseline method's historical response shape inside the legacy runner only.

- [x] **Step 4: Migrate representative lifecycle scenarios first**

Start with:

```text
position-broker-reject-usd-jpy
position-broker-exception-usd-jpy
position-broker-not-found-usd-jpy
position-pending-timeout-usd-jpy
```

Then migrate linkage/close scenarios if the shared model remains small and clear.

- [x] **Step 5: Run focused tests**

```sh
.venv/bin/python -m pytest -q tests/differential/test_harness_contract.py \
  -k 'broker or position'
```

**Completion criterion:** Scenario input, not runner-specific state setup, is the single source of Broker query/command responses for migrated cases; both runners prove exact sequence consumption.

---

### Task 3: Add Analysis Multi-Selection Coverage and Bootstrap Provenance

**Files:**
- Modify/add: `tests/differential/scenarios/analysis-*.json`
- Modify: `tests/differential/test_harness_contract.py`
- Modify: `tests/differential/test_baseline_reproducibility.py`
- Possibly modify: `tests/differential/baseline_contract.json`
- Read: `tests/fixtures/analysis_oracle_*.json`

**Interfaces:**
- Consumes: raw OANDA candle bytes/specs and current lossless analysis trace surfaces.
- Produces: at least one real-strategy scenario with multiple selected candidates/final plans, plus an explicit record of the bootstrap oracle relationship.

- [x] **Step 1: Search deterministic input variants for multiple selected plans**

Vary only raw frame spec/current price/decision time in a scratch probe. Do not put expected outputs into scenario JSON.

- [x] **Step 2: Add one real-strategy multiple-selected scenario**

Require:

```python
assert len(event["candidates"]["selected"][mode]) >= 2
assert len(event["semantic_plans"]) >= 2
```

Also assert final order and reason ordering.

- [x] **Step 3: Record bootstrap oracle provenance**

Either:

1. Add an explicit test proving each existing `analysis_oracle_*.json` agrees with the exact baseline trace on the overlapping fields; or
2. Record the oracle hashes and a documented incompatibility/retirement decision in baseline provenance.

Do not silently assume the existing oracle came from `eff331c`.

- [x] **Step 4: Run analysis gates**

```sh
.venv/bin/python -m pytest -q tests/differential/test_harness_contract.py \
  -k analysis
```

**Completion criterion:** The matrix includes zero, one, and multiple final-plan real-strategy outcomes, and the old oracle's relationship to `eff331c` is executable or explicitly recorded.

---

### Task 4: Add Failure-Path and Atomicity Tests

**Files:**
- Modify: `tests/differential/test_harness_contract.py`
- Modify: `tests/differential/test_baseline_reproducibility.py`
- Modify: `tests/differential/cli.py`
- Modify if needed: `tests/differential/orchestrator.py`
- Modify if needed: `tests/differential/worktree.py`

**Interfaces:**
- Consumes: `_update_golden`, `LegacyProcessOutcome`, `baseline_worktree`.
- Produces: executable proof that failures leave the previous golden set intact and temporary worktrees/directories cleaned.

- [x] **Step 1: Test capture failure rollback**

Monkeypatch the second scenario capture to raise. Hash the existing golden directory before and after. Assert byte identity and no `.replacement`/`.backup` directories remain.

- [x] **Step 2: Test replacement failure rollback**

Inject failure at the replacement rename. Assert the old golden directory is restored and valid.

- [x] **Step 3: Test subprocess timeout/signal outcome**

Assert `LegacyProcessError.outcome` includes `timed_out`, return code/signal, stdout, and stderr.

- [x] **Step 4: Test exceptional worktree cleanup**

Raise inside `baseline_worktree(...)`; assert the temporary worktree registration is removed and exit HEAD/clean verification still ran.

- [x] **Step 5: Run focused failure-path tests**

```sh
.venv/bin/python -m pytest -q tests/differential/test_harness_contract.py \
  -k 'golden or timeout or worktree or rollback'
```

**Completion criterion:** Every injected failure leaves the prior golden set byte-identical and no temporary worktree/replacement path remains.

---

### Task 5: Correct Documentation Scope

**Files:**
- Modify: `docs/differential-verification.md`
- Modify if needed: `docs/architecture-migration.md`
- Modify if needed: `docs/migration-map.md`

- [x] **Step 1: State live scope precisely**

Use this wording or an equivalent exact statement:

```text
The legacy live differential driver executes the real scheduler methods
exe_manage(), mode1(), and mode2(). Analysis, Position, candle, broker, and
notification collaborators are deterministic test doubles. This proves
scheduler decision and call-order parity, not full legacy live end-to-end parity.
```

- [x] **Step 2: Document raw quote/Broker response schema**

Include how each response is consumed exactly once and how underflow/leftovers fail.

- [x] **Step 3: Document golden rollback guarantees actually covered by tests**

Avoid claiming process-crash atomicity unless the implementation/test proves it.

**Completion criterion:** A new agent can distinguish scheduler parity, service parity, API wire compliance, and practice acceptance without reading runner internals.

---

### Task 6: Final Golden and Manifest Regeneration

**Prerequisite:** Tasks 1–5 green. No runner/schema/allowlist edits remain.

**Files:**
- Regenerate: `tests/differential/golden/eff331c2367570dcb8bc35a323a382e8255eda7b/*.trace.json`
- Regenerate: `tests/differential/golden/eff331c2367570dcb8bc35a323a382e8255eda7b/manifest.json`
- Modify only if observed differences require review: `tests/differential/intentional_deltas.json`

- [x] **Step 1: Run Ruff before capture**

```sh
.venv/bin/python -m ruff check tests/differential
```

- [x] **Step 2: Run harness contracts before capture**

```sh
.venv/bin/python -m pytest -q tests/differential/test_harness_contract.py
```

- [x] **Step 3: Regenerate the complete set only**

```sh
.venv/bin/python tests/differential/cli.py update-golden \
  --all \
  --legacy-ref eff331c2367570dcb8bc35a323a382e8255eda7b \
  --confirm-baseline-sha eff331c2367570dcb8bc35a323a382e8255eda7b
```

- [x] **Step 4: Verify scenario and manifest counts**

```sh
.venv/bin/python - <<'PY'
from tests.differential.golden import load_manifest
from tests.differential.scenario import load_all_scenarios

scenarios = load_all_scenarios()
manifest = load_manifest()
assert len(scenarios) == len(manifest["scenarios"])
assert set(manifest["scenarios"]) == {item.scenario_id for item in scenarios}
print(len(scenarios))
PY
```

**Completion criterion:** Manifest validation passes before comparison; there are no orphan, missing, stale, or partially updated traces.

---

### Task 7: Final Acceptance and Read-Only Review

- [x] **Step 1: Fast harness and CLI**

```sh
.venv/bin/python -m pytest -q tests/differential/test_harness_contract.py
.venv/bin/python tests/differential/cli.py compare-current --all
.venv/bin/python -m pytest -q tests/differential/test_current_against_golden.py
```

Expected: all green; every selected allowlist entry applied exactly once.

- [x] **Step 2: Provenance and determinism**

```sh
.venv/bin/python tests/differential/cli.py verify-baseline \
  --all \
  --legacy-ref eff331c2367570dcb8bc35a323a382e8255eda7b

.venv/bin/python -m pytest -q \
  tests/differential/test_baseline_reproducibility.py \
  --run-baseline-replay \
  -m baseline_replay
```

Expected: exact commit/tree, all traces reproducible, every scenario byte-equal over two fresh subprocess runs.

- [x] **Step 3: Repository gates**

```sh
.venv/bin/python -m pytest -q -m 'not integration and not baseline_replay'
.venv/bin/python -m ruff check src tests
.venv/bin/python -m compileall -q src tests
```

- [x] **Step 4: Check isolation residue**

```sh
git worktree list --porcelain
git status --short
```

Expected: only the main worktree; no differential artifact directories outside ignored `build/differential`.

- [x] **Step 5: Run independent read-only review**

Review specifically for:

- new-vs-new/shared-helper false parity;
- field pruning and non-price rounding;
- broad or multiply applied allowlist entries;
- current/legacy network or import leakage;
- stale/partial manifest provenance;
- scenario coverage versus the original Steps 9–11.

- [x] **Step 6: Stage and commit only scoped files**

Inspect first:

```sh
git status --short
git diff -- tests/differential docs/differential-verification.md \
  docs/architecture-migration.md docs/migration-map.md
```

Stage explicit paths. Exclude `.vscode/` and any unrelated user work.

**Completion criterion:** Every original-plan completion condition is green, the independent review has no blocking finding, and the commit contains only differential/docs changes.

---

## First Action for the Next Agent

Start with Task 1 only. Add `test_live_spread_boundary_trace_uses_pair_precision`, verify the two binary-float failures, and move live scenario input to raw OANDA pricing responses. Do not regenerate golden yet.

After Task 1 is green, update this document's checkboxes or append a dated checkpoint before starting Task 2.
