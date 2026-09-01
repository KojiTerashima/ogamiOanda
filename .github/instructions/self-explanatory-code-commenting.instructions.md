---
description: "Use when writing or editing comments: prefer self-explanatory code and comments that explain why, not what. Based on github/awesome-copilot self-explanatory-code-commenting."
applyTo: "**/*.{py,md,yaml,yml,json}"
---

# Self-Explanatory Code Commenting

Write code that explains itself through names, structure, and tests. Add comments only when they preserve useful context that is not obvious from the code.

## Commenting Rules

- Do not add comments that restate the next line of code.
- Prefer clearer names or smaller functions over explanatory comments.
- Use comments for non-obvious business rules, external API constraints, risk controls, precision choices, time handling, or compatibility reasons.
- Keep TODO, FIXME, WARNING, SECURITY, and PERF notes specific and actionable.
- Do not keep commented-out code or historical changelog comments in source files.
- When comments are needed, write them as durable project knowledge, not as a record of the current edit.
