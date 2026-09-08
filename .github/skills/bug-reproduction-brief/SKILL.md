---
name: bug-reproduction-brief
description: "Use for an explicit reproduction-only or diagnosis-only deliverable. Exclude fix requests as a stopping point: establish the reproduction, then return control to implementation."
---

# Bug Reproduction Brief

Establish the smallest evidence-backed failure before diagnosis or repair.

1. Record the exact error or incorrect output, smallest known input, target commit, and inspectable environment facts.
2. State expected and actual behavior as separate observable results, without embedding a suspected cause.
3. Reduce the report to the smallest safe test, script, fixture, or request that still fails.
4. Run the minimal reproduction at least twice when safe. For intermittent failures, record frequency and duration instead of claiming determinism.
5. Preserve commands, sanitized output, and source paths as evidence. Label second-hand reports and unresolved conditions explicitly.

For a reproduction-only or diagnosis-only request, stop with this brief:

```markdown
# Bug Reproduction Brief

- Target and commit:
- Environment:
- Expected:
- Actual:
- Minimal steps and fixture:
- Reproduced: yes / no / intermittent
- Evidence:
- Unknowns:
- Safe next hypothesis:
```

For a fix request, keep the reproduction as evidence and return to the implementation workflow; the brief is not a second approval gate.

Use read-only or reversible discovery and never mutate production data to reproduce a failure.