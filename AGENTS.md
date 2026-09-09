# ogamiOanda Agent Guidance

This repository migrates the Python/OANDA trading system while preserving observable behavior.

## Source and compatibility boundaries

- `src/ogami_oanda/` is production source. Root-level Python modules are compatibility surfaces until migration removes them.
- Preserve existing characterization and contract behavior unless the requested change explicitly alters it. Treat order, position, candle, backtest, and migration boundaries as high risk.
- `config/settings.example.yaml` is the committed configuration template. Keep `config/settings.yaml` private and ignored; never read, copy, log, or commit its values.

## Work and approval boundaries

- Complete user-authorized, in-scope implementation and correct failures caused by the change.
- Focused offline pytest checks under `tests/` are pre-authorized.
- Obtain explicit authorization before integration checks, practice acceptance, live trading, credentialed commands, destructive actions, or external mutations.

## Conditional documentation routes

Read these only when the change or question matches the route:

- Current program overview and documentation: `README.md`, `docs/README.md`
- Directory/file ownership: `docs/structure.md`; class/function lookup: `docs/reference/README.md`
- CLI and configuration: `docs/usage.md`; behavior contracts: `docs/specification.md`
- Test commands and external boundaries: `tests/README.md`
- Layer or live-flow changes: `docs/architecture-migration.md`
- Legacy parity or golden traces: `docs/differential-verification.md`
- Migration-state questions: `docs/migration-map.md`

## Archived material

- `archive/retired/` contains historical bundles, not current production source or instructions.
- Do not read, search, extract, import, or execute retired contents during ordinary work. Access them only when the user requests historical investigation/restoration or the task specifically requires a legacy comparison; start with `docs/archive-policy.md` and the manifest.
- `.rgignore` excludes `archive/retired/` from ordinary `rg` searches. Explicit paths, `rg --no-ignore`, and other tools can bypass this; the instruction above remains the agent boundary.
- `archive/classPositionForTest.py` is still imported by the root compatibility layer; it is deliberately outside `archive/retired/` and remains searchable.
- Root compatibility modules still used by tests remain outside the retired archive. Do not move them based only on age or lack of production imports.

## Completion

Completion requires the requested implementation, correction of failures caused by it, relevant risk-scaled offline verification, and a final inspection of the diff and repository status. Report changed files, verification results, and any unverified boundary.
