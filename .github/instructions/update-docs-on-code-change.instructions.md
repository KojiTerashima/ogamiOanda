---
description: "Use when code changes affect setup, configuration, public behavior, APIs, scripts, or migration status: update related documentation. Based on github/awesome-copilot update-docs-on-code-change."
applyTo: "**/*.{py,md,yaml,yml,toml,json}"
---

# Update Documentation On Code Change

Keep documentation synchronized with behavior. When changing code or configuration, check whether README files, docs, examples, or config templates also need updates.

## Update Docs When

- Setup, dependencies, commands, or test execution changes.
- Configuration keys, defaults, environment variables, or token handling changes.
- Public module behavior, APIs, strategy semantics, backtest behavior, or order handling changes.
- Migration status, compatibility guarantees, or legacy-vs-new implementation mapping changes.
- Examples, fixtures, or expected outputs become stale.

## Documentation Standards

- Write directly about the current behavior. Do not announce that documentation was updated.
- Include concise examples when they help a user run or verify the feature.
- Keep paths, commands, and config samples accurate for this repository.
- If no documentation update is needed, be ready to state why in the final summary.
