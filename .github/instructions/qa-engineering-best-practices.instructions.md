---
description: "Use when adding, changing, or reviewing tests: apply QA engineering best practices for deterministic, focused, maintainable tests. Based on github/awesome-copilot qa-engineering-best-practices."
applyTo: "**/test*.py,**/tests/**/*.py"
---

# QA Engineering Best Practices

Treat tests as first-class code. Prefer focused tests that verify observable behavior and fail with useful information.

## Test Rules

- Each test should verify one coherent behavior.
- Use descriptive names that read like a scenario, such as `test_returns_expected_value_when_condition`.
- Prefer exact assertions over truthiness checks.
- Keep test data minimal and local to the behavior under test.
- Avoid real production data, personal information, tokens, and environment-specific values.
- Mock external boundaries such as OANDA API calls, network clients, clocks, and filesystem side effects when needed. Do not mock pure domain logic unnecessarily.
- Keep tests deterministic. Avoid sleeps, ordering dependencies, shared mutable state, and network calls.
- Cover edge cases around empty inputs, invalid config, API errors, order rejection, precision, and timezone-sensitive candle data.
