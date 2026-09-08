---
name: secret-scanning
description: "Use for GitHub secret-scanning configuration, push protection, custom patterns, blocked pushes, or alerts and remediation. This owns GitHub product workflows; explicit source vulnerability audits belong to security-review."
---

# Secret Scanning

Handle the requested GitHub secret-scanning workflow without expanding into a general source audit.

1. Identify the requested repository or organization scope and whether the task concerns configuration, push protection, custom patterns, a blocked push, or an alert.
2. For push protection and bypass workflows, load [push protection](references/push-protection.md).
3. For provider or organization-specific detection, load [custom patterns](references/custom-patterns.md).
4. For alert triage, rotation, dismissal, validity, or remediation, load [alerts and remediation](references/alerts-and-remediation.md).
5. Report the settings or alert state inspected, recommended action, required permissions, and any external change that still needs approval.

Treat credential rotation, repository setting changes, bypasses, dismissals, and alert mutations as external effects requiring explicit authorization. Keep secret values out of commands, logs, and reports.