---
description: "Use when editing config, YAML, environment variables, API clients, logging, or examples: protect secrets and avoid leaking sensitive data. Based on github/awesome-copilot security-and-owasp/exclude-prompt-data guidance."
applyTo: "**/*.{py,yaml,yml,toml,json,md,env,example}"
---

# Secrets And Config Security

Treat API tokens, account IDs, passwords, private URLs, and trading account configuration as sensitive. Prefer secure defaults and avoid leaking operational details.

## Rules

- Never hardcode real API keys, tokens, passwords, account IDs, or private hostnames in source code, docs, tests, or examples.
- Keep real settings out of committed files. Use example files with placeholder values.
- Do not log tokens, authorization headers, account identifiers, raw config dictionaries, or exception details that may include secrets.
- Validate required configuration at startup or boundary entry points with clear, non-sensitive error messages.
- Prefer environment variables or ignored local config for secrets.
- In tests, use explicit fake values such as `DUMMY_TOKEN`, `example-account`, or `https://example.com`.
- When handling external API errors, preserve enough context for debugging without exposing credentials or sensitive payloads.
