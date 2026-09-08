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

- Test commands and external boundaries: `tests/README.md`
- Layer or live-flow changes: `docs/architecture-migration.md`
- Legacy parity or golden traces: `docs/differential-verification.md`
- Migration-state questions: `docs/migration-map.md`

## Completion

Completion requires the requested implementation, correction of failures caused by it, relevant risk-scaled offline verification, and a final inspection of the diff and repository status. Report changed files, verification results, and any unverified boundary.
