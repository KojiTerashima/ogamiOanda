# Issue/PR Templates (20 Tasks)

This document contains ready-to-copy Issue body and PR body templates for the 20-task improvement plan.

## 01. CFG-01 Configuration Schema
### Issue Body
```md
## Title
[CFG-01] Define configuration schema (required keys/types/validation)

## Background
Move from hard-coded settings to YAML safely.

## Goal
Catch missing/invalid configuration before runtime.

## Scope
- Add `config/schema.py`
- Define required keys and type checks
- Add clear validation error messages

## Done Criteria
- Missing keys fail fast with readable errors
- Type checks exist for critical config values

## Acceptance Criteria
- [ ] Required key validation implemented
- [ ] Type validation implemented
- [ ] Tests for valid/invalid config

## Estimate
0.5 day
```

### PR Body
```md
## Related Issue
CFG-01

## Summary
Implemented config schema and validation rules.

## Changes
- Added `config/schema.py`
- Added validation logic and error messages
- Added tests for valid/invalid cases

## Validation
- [ ] `ruff check .`
- [ ] `pytest`

## Risks / Rollback
Low. Revert schema module if needed.
```

## 02. CFG-02 YAML Loader
### Issue Body
```md
## Title
[CFG-02] Implement YAML settings loader

## Background
Need secure and consistent YAML loading.

## Goal
Load `settings.yaml` using `yaml.safe_load`.

## Scope
- Add `config/loader.py`
- Handle file-not-found and parse errors

## Done Criteria
- Loader returns dict on success
- Loader raises clear errors on failure

## Acceptance Criteria
- [ ] Normal load works
- [ ] Missing file error is clear
- [ ] Parse error is clear

## Estimate
0.5 day
```

### PR Body
```md
## Related Issue
CFG-02

## Summary
Added YAML loader with robust error handling.

## Changes
- Added `config/loader.py`
- Added safe_load usage
- Added tests for failure modes

## Validation
- [ ] `ruff check .`
- [ ] `pytest`
```

## 03. CFG-03 tokens.py Compatibility Wrapper
### Issue Body
```md
## Title
[CFG-03] Convert `tokens.py` into YAML-backed compatibility wrapper

## Background
Existing modules depend on `import tokens as tk`.

## Goal
Keep current access style while sourcing values from YAML.

## Scope
- Refactor `tokens.py` to load from YAML
- Preserve existing attribute names
- Add clear startup errors for missing keys

## Done Criteria
- Existing imports continue to work
- Values are loaded from YAML

## Acceptance Criteria
- [ ] Main scripts run without import changes
- [ ] Wrapper maps all required keys

## Estimate
1 day
```

### PR Body
```md
## Related Issue
CFG-03

## Summary
Refactored `tokens.py` to compatibility wrapper backed by YAML settings.

## Changes
- Updated `tokens.py`
- Added mapping from YAML keys to legacy names
- Added startup validation

## Validation
- [ ] `ruff check .`
- [ ] Main run smoke test

## Risks / Rollback
Medium. Roll back `tokens.py` to previous static version.
```

## 04. CFG-04 Example Settings and Git Ignore
### Issue Body
```md
## Title
[CFG-04] Add `settings.example.yaml` and ignore local `settings.yaml`

## Goal
Keep secrets out of git while preserving onboarding.

## Scope
- Add `settings.example.yaml`
- Ensure `settings.yaml` is ignored

## Done Criteria
- Example tracked, real settings untracked

## Acceptance Criteria
- [ ] Example file exists
- [ ] Local settings are gitignored

## Estimate
0.5 day
```

### PR Body
```md
## Related Issue
CFG-04

## Summary
Added sample settings and ensured local secrets are not committed.

## Changes
- Added `settings.example.yaml`
- Updated ignore rules

## Validation
- [ ] Fresh clone setup works
```

## 05. CFG-05 Add PyYAML Dependency
### Issue Body
```md
## Title
[CFG-05] Add PyYAML dependency

## Goal
Provide declared dependency for YAML support.

## Scope
- Update `pyproject.toml`
- Update lock file

## Done Criteria
- `import yaml` works in venv

## Acceptance Criteria
- [ ] Dependency installed in clean environment

## Estimate
0.5 day
```

### PR Body
```md
## Related Issue
CFG-05

## Summary
Added PyYAML to project dependencies.

## Validation
- [ ] `poetry install` succeeds
- [ ] `python -c "import yaml"` succeeds
```

## 06. CFG-06 Configuration Docs
### Issue Body
```md
## Title
[CFG-06] Document configuration setup and secret handling

## Goal
Make onboarding reproducible and safe.

## Scope
- Update `docs/configuration.md`
- Add troubleshooting section

## Done Criteria
- New developer can configure app from docs only

## Acceptance Criteria
- [ ] Setup steps verified end-to-end

## Estimate
0.5 day
```

### PR Body
```md
## Related Issue
CFG-06

## Summary
Improved configuration documentation and secret handling guidance.

## Validation
- [ ] Docs walkthrough tested
```

## 07. ARC-01 Limit tokens Access to Entry Layer
### Issue Body
```md
## Title
[ARC-01] Restrict `tokens` usage to entry layer

## Goal
Reduce coupling and improve dependency direction.

## Scope
- Keep direct config imports only in entrypoints
- Pass config through constructors/DI

## Done Criteria
- Domain/application layers no longer import tokens directly

## Acceptance Criteria
- [ ] `grep` shows reduced `import tokens` in core modules

## Estimate
1 day
```

### PR Body
```md
## Related Issue
ARC-01

## Summary
Moved configuration access to entry layer and injected dependencies downstream.

## Validation
- [ ] `ruff check .`
- [ ] `pytest`
- [ ] Smoke run
```

## 08. ARC-02 AppConfig Typed Access
### Issue Body
```md
## Title
[ARC-02] Introduce typed `AppConfig`

## Goal
Avoid fragile dict-style config access.

## Scope
- Add typed config object
- Replace key accesses in target modules

## Done Criteria
- Critical modules use typed config

## Acceptance Criteria
- [ ] AppConfig present
- [ ] Replaced direct key access in target scope

## Estimate
1 day
```

### PR Body
```md
## Related Issue
ARC-02

## Summary
Introduced typed `AppConfig` and migrated selected modules.

## Validation
- [ ] `ruff check .`
- [ ] `pytest`
```

## 09. ARC-03 Dependency Container
### Issue Body
```md
## Title
[ARC-03] Add dependency container for object construction

## Goal
Centralize object creation and enable stubs/fakes.

## Scope
- Add container module
- Route main construction through container

## Done Criteria
- Main boot path uses container

## Acceptance Criteria
- [ ] Fake dependencies usable in tests

## Estimate
1 day
```

### PR Body
```md
## Related Issue
ARC-03

## Summary
Added dependency container and routed bootstrapping through it.

## Validation
- [ ] `ruff check .`
- [ ] `pytest`
- [ ] Main startup check
```

## 10. OAN-01 Split Oanda (Market Data)
### Issue Body
```md
## Title
[OAN-01] Split market-data responsibilities from `classOanda.py`

## Goal
Increase cohesion by extracting market-data logic.

## Scope
- Add `oanda_market_data.py`
- Delegate from facade

## Done Criteria
- Candle/price logic extracted

## Acceptance Criteria
- [ ] Existing interface compatibility preserved

## Estimate
1 day
```

### PR Body
```md
## Related Issue
OAN-01

## Summary
Extracted market-data operations into dedicated module.

## Validation
- [ ] Regression checks for candle/price APIs
```

## 11. OAN-02 Split Oanda (Orders/Trades)
### Issue Body
```md
## Title
[OAN-02] Split order/trade responsibilities from `classOanda.py`

## Goal
Reduce god-class complexity.

## Scope
- Add `oanda_orders.py`
- Add `oanda_trades.py`

## Done Criteria
- Order/trade methods delegated to modules

## Acceptance Criteria
- [ ] Place/cancel order flow verified
- [ ] Trade detail flow verified

## Estimate
1 day
```

### PR Body
```md
## Related Issue
OAN-02

## Summary
Separated order/trade logic into dedicated modules.

## Validation
- [ ] Regression tests/smoke checks
```

## 12. OAN-03 Remove Duplicate Helpers
### Issue Body
```md
## Title
[OAN-03] Remove duplicated helper functions from `classOanda.py`

## Goal
Single source of truth in `classOandaSupport.py`.

## Scope
- Delete duplicated helper definitions
- Keep only delegated usage

## Done Criteria
- No duplicate helper definitions remain

## Acceptance Criteria
- [ ] Helper calls resolve only to support module

## Estimate
0.5 day
```

### PR Body
```md
## Related Issue
OAN-03

## Summary
Deleted duplicate helper functions and unified helper source.

## Validation
- [ ] `ruff check .`
- [ ] Core API smoke tests
```

## 13. TURN-01 Split Turn Inspection (State + BB)
### Issue Body
```md
## Title
[TURN-01] Split `fTurnInspection.py` (state + BB analysis)

## Goal
Improve maintainability of trend analysis logic.

## Scope
- Add `turn_state.py`
- Add `turn_bb_analysis.py`

## Done Criteria
- State and BB analysis physically separated

## Acceptance Criteria
- [ ] Existing behavior preserved

## Estimate
1 day
```

### PR Body
```md
## Related Issue
TURN-01

## Summary
Separated runtime state and BB analysis into dedicated modules.

## Validation
- [ ] Regression checks for trend signal paths
```

## 14. TURN-02 Split Turn Inspection (Order Rules)
### Issue Body
```md
## Title
[TURN-02] Split order-rule logic from `fTurnInspection.py`

## Goal
Isolate rule engine for easier testing.

## Scope
- Add `turn_order_rules.py`
- Delegate order creation rules

## Done Criteria
- Order-rule logic moved from monolith file

## Acceptance Criteria
- [ ] Existing order decisions unchanged

## Estimate
1 day
```

### PR Body
```md
## Related Issue
TURN-02

## Summary
Extracted order-rule logic into dedicated module.

## Validation
- [ ] Unit tests for key rule branches
```

## 15. POS-01 Unify Position Core
### Issue Body
```md
## Title
[POS-01] Extract shared logic from `classPosition*` into `position_core.py`

## Goal
Reduce duplicated behavior between production and test classes.

## Scope
- Create `position_core.py`
- Move shared operations

## Done Criteria
- Duplicate logic reduced materially

## Acceptance Criteria
- [ ] Shared logic centralized

## Estimate
1 day
```

### PR Body
```md
## Related Issue
POS-01

## Summary
Extracted shared position logic to `position_core.py`.

## Validation
- [ ] Regression checks for position lifecycle
```

## 16. POS-02 Strategy for Test/Prod Differences
### Issue Body
```md
## Title
[POS-02] Use strategy adapter for prod/test differences

## Goal
Move environment-specific branching out of core logic.

## Scope
- Add execution adapter abstraction
- Inject adapter in position control

## Done Criteria
- Core logic free from test/prod conditionals

## Acceptance Criteria
- [ ] Adapter-based switching verified

## Estimate
1 day
```

### PR Body
```md
## Related Issue
POS-02

## Summary
Introduced adapter strategy for environment-specific behavior.

## Validation
- [ ] Adapter tests pass
```

## 17. TEST-01 Expand Pure Function Tests
### Issue Body
```md
## Title
[TEST-01] Expand `turn_analysis_core` unit tests

## Goal
Increase regression coverage for decision rules.

## Scope
- Add boundary/edge cases
- Clarify behavior via test names

## Done Criteria
- 15+ test cases in this area

## Acceptance Criteria
- [ ] Boundary conditions covered

## Estimate
0.5 day
```

### PR Body
```md
## Related Issue
TEST-01

## Summary
Expanded pure-function unit tests with edge and boundary cases.

## Validation
- [ ] `pytest tests/test_turn_analysis_core.py`
```

## 18. TEST-02 Stub-based Integration Tests
### Issue Body
```md
## Title
[TEST-02] Add integration tests with Fake Oanda

## Goal
Validate workflows without external API dependency.

## Scope
- Implement Fake Oanda
- Test position control workflow

## Done Criteria
- Core flow reproducible offline

## Acceptance Criteria
- [ ] Tests deterministic and repeatable

## Estimate
1 day
```

### PR Body
```md
## Related Issue
TEST-02

## Summary
Added stub-based integration tests for core trading workflow.

## Validation
- [ ] Offline integration tests pass
```

## 19. CI-01 Standard Quality Gate
### Issue Body
```md
## Title
[CI-01] Standardize quality gate (`ruff` + `pytest`)

## Goal
Ensure consistent pre-merge checks.

## Scope
- Define standard check command(s)
- Document usage

## Done Criteria
- One command executes lint + tests

## Acceptance Criteria
- [ ] Team can run same checks locally

## Estimate
0.5 day
```

### PR Body
```md
## Related Issue
CI-01

## Summary
Standardized lint/test quality gate commands and docs.

## Validation
- [ ] Clean run in local environment
```

## 20. CI-02 PR Template Governance
### Issue Body
```md
## Title
[CI-02] Enforce PR template fields (scope/validation/risk)

## Goal
Improve review quality and traceability.

## Scope
- Add PR template
- Require key review sections

## Done Criteria
- New PRs follow template sections

## Acceptance Criteria
- [ ] Template includes impact, validation, rollback

## Estimate
0.5 day
```

### PR Body
```md
## Related Issue
CI-02

## Summary
Added PR governance template for consistent review quality.

## Validation
- [ ] New PR creation shows required sections
```
