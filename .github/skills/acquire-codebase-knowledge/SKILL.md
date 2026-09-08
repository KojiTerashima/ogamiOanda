---
name: acquire-codebase-knowledge
description: "Use when the user explicitly requests codebase mapping, documentation, or onboarding. Exclude routine edits, feature implementation, and bug fixes unless repository-level discovery is requested."
license: MIT
compatibility: "Cross-platform. Requires Python 3.8+ and git."
argument-hint: "Optional focus area, such as architecture or testing and concerns"
---

# Acquire Codebase Knowledge

Produce `STACK.md`, `STRUCTURE.md`, `ARCHITECTURE.md`, `CONVENTIONS.md`, `INTEGRATIONS.md`, `TESTING.md`, and `CONCERNS.md` under `docs/codebase/`.

Document only claims supported by inspected files or terminal output. Mark unresolved facts as `[TODO]`, team-intent decisions as `[ASK USER]`, and include concrete evidence paths in every output document.

1. Follow [the complete workflow](references/workflow.md), including scan, investigation, template population, and validation.
2. Load [the inquiry checkpoints](references/inquiry-checkpoints.md) while investigating and validating each document.
3. Load [stack detection guidance](references/stack-detection.md) only when manifests or file types leave the stack ambiguous.
4. Finish with a summary, all `[ASK USER]` questions, and any intent-versus-reality divergences.