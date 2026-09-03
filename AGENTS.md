# ogamiOanda Agent Entry Point

Read the shared workspace rules in `../AGENTS.md`, then `.github/AGENTS.md` and `.github/copilot-instructions.md`.
This repository is the Python/OANDA migration project. Prefer `src/ogami_oanda/`, `tests/`, and the existing characterization and contract tests when validating changes.
Treat `config/settings.example.yaml` as the committed template. Keep local credentials in the ignored `config/settings.yaml` and never copy them into shared assets.