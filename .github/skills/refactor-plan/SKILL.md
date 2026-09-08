---
name: refactor-plan
description: "Use only when the requested deliverable is a plan-only refactor proposal. Investigate boundaries, sequence changes, risks, and verification without turning an implementation request into a planning stop."
---

# Refactor Plan

Prepare a repository-specific plan without editing implementation files.

1. Inspect the controlling implementation, tests, configuration, documentation, callers, and ownership boundaries.
2. Define current and target behavior, including contracts that must remain stable.
3. List affected files and dependencies, then sequence the smallest coherent phases.
4. Give each phase a focused verification criterion and identify rollback for risky or irreversible work.
5. Record assumptions, scope exclusions, and decisions that genuinely block implementation.

Use this output shape:

```markdown
# Refactor Plan: [title]

## Current State
## Target State
## Affected Files
## Execution Phases
## Verification
## Risks and Recovery
## Assumptions and Open Decisions
```

Return the completed plan directly. Add a confirmation gate only when the user requested one; implementation requests stay with the implementation workflow.