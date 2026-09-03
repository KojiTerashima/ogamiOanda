# ogamiOanda Copilot Instructions

Apply the shared workspace rules from [Copilot instructions](../../.github/copilot-instructions.md) and [AGENTS.md](../../AGENTS.md), then the repository-specific guidance in [`.github/AGENTS.md`](AGENTS.md).

- Keep migration work centered on `src/ogami_oanda/` and focused tests in `tests/`.
- Use characterization and contract tests to preserve legacy behavior while migrating.
- Treat `config/settings.example.yaml` as the safe public template. Never expose credentials or values from `config/settings.yaml`.