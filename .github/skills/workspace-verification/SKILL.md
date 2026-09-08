---
name: workspace-verification
description: Use when verifying work from the shared workspace before a repository-specific verification route has been selected.
---

# Workspace Verification

Route verification to the repository that owns the requested or changed paths.

1. Select the owning repository from the task scope and changed paths.
2. Read its root `AGENTS.md` and the verification documentation it routes to.
3. Inspect that repository's status and relevant diff.
4. Run the narrowest relevant offline check from its documented verification route.
5. Report the check outcomes and any unverified boundaries with the final diff and status summary.
