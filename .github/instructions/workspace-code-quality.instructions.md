---
description: "Use for implementation and review work: keep changes focused, explicit, testable, and consistent with the owning repository."
applyTo: "**"
---

# Shared Code Quality

- Identify the code path that decides the behavior before editing.
- Prefer existing abstractions and explicit names over speculative refactors.
- Preserve public behavior unless the task requires a change.
- Add deterministic tests for changed behavior and boundary cases.
- Validate with the narrowest useful command immediately after each substantive change.
- Review the final diff for unrelated changes, prompt echoes, and accidental sensitive data.