---
name: workspace-verification
description: "Use when verifying implementation changes in BFScalping or ogamiOanda: inspect the diff, run focused tests, and check configuration safety."
---

# Workspace Verification

1. Read the nearest `AGENTS.md` and identify the touched behavior.
2. Inspect `git diff --check` and the changed-file list for accidental or sensitive content.
3. Run the narrowest relevant test or type/lint command first.
4. For trading or migration changes, include rejection, precision, timezone, and offline-boundary cases as applicable.
5. Run broader repository checks only when the focused check passes and the change scope warrants it.
6. Report commands and outcomes without printing secrets or full private configuration.