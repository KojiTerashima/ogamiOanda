---
description: "Use when reviewing changes: prioritize correctness, security, test coverage, maintainability, and architectural consistency. Based on github/awesome-copilot code-review-generic."
applyTo: "**"
excludeAgent: ["coding-agent"]
---

# Generic Code Review

When performing a code review, respond in Japanese unless the user asks otherwise. Lead with findings ordered by severity. Focus on defects, risks, regressions, missing tests, and unclear behavior before style preferences.

## Priorities

- Critical: security vulnerabilities, exposed secrets, data loss, incorrect trading or order behavior, breaking API or configuration changes.
- Important: missing tests for critical paths, brittle error handling, excessive coupling, performance risks, or drift from existing architecture.
- Suggestion: readability, naming, documentation gaps, and small refactors that are useful but not blocking.

## Review Standards

- Reference concrete files and behavior.
- Explain why each issue matters and suggest a practical fix.
- Check tests for deterministic behavior, meaningful assertions, and boundary cases.
- Check Python code for explicit exceptions, clear names, dependency boundaries, and compatibility with existing pytest patterns.
- Check documentation and examples when public behavior, configuration, setup, or migration paths change.
- Avoid broad rewrites unless they are required to remove a real risk.
