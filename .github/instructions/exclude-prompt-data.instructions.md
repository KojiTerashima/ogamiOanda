---
description: "Write only the resulting content into files. Never echo prompt instructions, rationale, or meta-commentary into documentation, comments, or code being produced from a prompt. Based on github/awesome-copilot exclude-prompt-data."
applyTo: "**"
---

# Exclude Prompt Data

When editing files, write the result as if it naturally belongs in the project. Do not copy the user's prompt wording, rationale, or task framing into source code, comments, documentation, examples, or configuration.

## Rules

- Do not add phrases such as "as requested", "per the prompt", "per your instruction", or "this was updated to".
- Do not add comments that narrate the edit. Comments should describe durable behavior, constraints, or non-obvious intent.
- Do not paste contextual details from the prompt unless the user explicitly asks for verbatim insertion.
- Use generic placeholder data in examples. Do not reuse local secrets, real account IDs, API tokens, emails, hostnames, or organization-specific values from config files.
- For prompt, instruction, agent, or skill files, instructional text is the intended payload, but still avoid meta-commentary about the current edit.

## Self-Check

Before finishing a file edit, scan the diff for prompt echoes and remove them. A future reader should be able to understand the file without knowing the conversation that produced it.
