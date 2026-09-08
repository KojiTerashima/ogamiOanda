---
name: security-review
description: "Use only for an explicit source vulnerability audit of a user-requested file, directory, diff, or repository scope. Trace and verify source risks; GitHub secret-scanning configuration, push protection, and alerts belong to secret-scanning."
---

# Security Review

Audit only the source scope the user requested. If the scope is unclear, resolve it before scanning rather than defaulting to the entire repository.

1. Identify languages, frameworks, entry points, trust boundaries, and dependency manifests within scope.
2. Load [language patterns](references/language-patterns.md) for the detected stack and [vulnerability categories](references/vuln-categories.md) for relevant threat classes.
3. Trace untrusted input across files to sensitive sinks. Include authentication, authorization, injection, path, serialization, cryptography, data exposure, and business-logic risks when applicable.
4. Inspect hardcoded-secret exposure only within the requested source scope. GitHub secret-scanning settings and alert operations remain outside this workflow.
5. Audit dependencies only when their manifests are in scope, using [vulnerable packages](references/vulnerable-packages.md) as supporting guidance.
6. Re-read each candidate finding, account for framework protections or upstream validation, and discard unsupported claims.
7. Report findings by severity using [the report format](references/report-format.md), with concrete paths, behavior, evidence, confidence, and a targeted remediation.

Do not apply proposed patches unless the user requests implementation. If no vulnerability is verified, state the reviewed scope and residual unverified boundaries.