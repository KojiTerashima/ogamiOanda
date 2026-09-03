---
description: "Use when editing code, configuration, API clients, logs, tests, or documentation: protect secrets and operational data."
applyTo: "**/*.{py,yaml,yml,toml,json,md,env,example}"
---

# Shared Security

- Never hardcode real credentials, account identifiers, private hostnames, or authorization headers.
- Keep local secrets in ignored configuration or environment variables and use obvious placeholders in committed examples.
- Do not log raw configuration, tokens, order credentials, or external error payloads that may contain secrets.
- Keep tests offline and use fake values such as `DUMMY_TOKEN` and `example-account`.
- Treat live-trading flags and endpoint changes as requiring explicit review and focused verification.