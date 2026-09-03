---
description: "Use when adding or changing tests: write focused, deterministic tests for observable behavior and risk boundaries."
applyTo: "**/test*.py,**/tests/**/*.py"
---

# Shared Testing

- Keep each test focused on one coherent behavior with an exact assertion.
- Use descriptive scenario names and minimal local fixtures.
- Mock network, broker, clock, and filesystem boundaries where appropriate; do not mock pure domain logic.
- Cover empty input, invalid configuration, API failure, rejection, precision, and timezone-sensitive behavior when relevant.
- Avoid sleeps, ordering dependencies, shared mutable state, and real production data.