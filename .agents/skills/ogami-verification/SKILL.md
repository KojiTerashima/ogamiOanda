---
name: ogami-verification
description: Use when explicitly verifying completed ogamiOanda work or before completing changes that affect trading or migration behavior.
---

# Ogami Verification

Read [the maintained test guide](../../../tests/README.md) for current commands and external boundaries.

1. Inspect the relevant diff and status to identify affected behavior and risk.
2. Start with the affected pytest node or file.
3. For code changes, run the applicable Ruff check.
4. Use the full non-integration suite only for broad or high-risk changes.
5. Report checks run, results, and any unverified boundary.

Do not run integration, practice acceptance, live, or credentialed checks without explicit user authorization.
