# ogamiOanda Repository Guidance

Read the shared workspace rules in `../../AGENTS.md` and shared Copilot rules in `../../.github/copilot-instructions.md`.
This repository-specific guidance covers the Python/OANDA migration under `src/ogami_oanda/`.

## Validation

- Prefer focused pytest tests under `tests/` before broader suites.
- Preserve characterization and contract behavior unless a migration change explicitly updates it.
- Use `config/settings.example.yaml` for documentation and tests; do not expose values from `config/settings.yaml`.