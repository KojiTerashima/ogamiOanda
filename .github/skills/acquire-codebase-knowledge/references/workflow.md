# Codebase Knowledge Workflow

## Output Contract

Create exactly these files under `docs/codebase/`:

- `STACK.md`
- `STRUCTURE.md`
- `ARCHITECTURE.md`
- `CONVENTIONS.md`
- `INTEGRATIONS.md`
- `TESTING.md`
- `CONCERNS.md`

Every non-trivial claim must be traceable to inspected source, configuration, or terminal output. Mark unknown facts as `[TODO]`, intent-dependent decisions as `[ASK USER]`, and include a short evidence list with concrete paths in every document.

## Phases

Use this checklist:

```text
- [ ] Phase 1: Run scan and read intent documents
- [ ] Phase 2: Investigate each documentation area
- [ ] Phase 3: Populate all seven documents
- [ ] Phase 4: Validate evidence and present findings
```

### Phase 1: Scan and Read Intent

From the target project root, run:

```bash
python3 "$SKILL_ROOT/scripts/scan.py" --output docs/codebase/.codebase-scan.txt
```

Search for maintained `PRD`, `TRD`, `README`, `ROADMAP`, `SPEC`, and `DESIGN` files. Summarize stated project intent before inspecting source implementation.

### Phase 2: Investigate

Use the scan output and `inquiry-checkpoints.md` to inspect every documentation area. Load `stack-detection.md` only when multiple manifests, unfamiliar file types, or missing conventional manifests make the stack ambiguous.

Distinguish intended architecture from current structure. Record unsupported or team-owned decisions instead of guessing.

### Phase 3: Populate Templates

Copy and complete templates from `assets/templates/` in this order:

1. `STACK.md`: language, runtime, frameworks, production dependencies, and development tooling.
2. `STRUCTURE.md`: directory layout, entry points, generated areas, and key files.
3. `ARCHITECTURE.md`: layers, patterns, ownership boundaries, and data flow.
4. `CONVENTIONS.md`: naming, formatting, imports, errors, and observed practices.
5. `INTEGRATIONS.md`: external APIs, data stores, authentication, and monitoring.
6. `TESTING.md`: frameworks, organization, fixtures, mocking, and commands.
7. `CONCERNS.md`: verified debt, defects, security risks, performance risks, and fragile areas.

Complete core template sections by default. Add optional sections only when repository complexity provides useful evidence for them.

### Phase 4: Validate and Report

Validate every document against `inquiry-checkpoints.md`:

1. Confirm every required section has supported content or an explicit `[TODO]`.
2. Confirm every non-trivial claim has at least one evidence reference.
3. Repair unsupported claims, missing sections, or unmarked uncertainty and repeat validation.
4. Summarize all seven documents, list every `[ASK USER]` item as a numbered question, and highlight intent-versus-reality divergences.

## Focus Area Mode

When the user supplies a focus area, always complete Phase 1, finish focused documents first, and retain required sections with `[TODO]` in documents not yet analyzed. Validate all seven documents before completion.

## Investigation Gotchas

- **Monorepos:** inspect workspace declarations and map each package's independent dependencies and conventions.
- **Outdated intent docs:** cross-check README and design claims against current source structure.
- **Path aliases:** resolve configured aliases to real paths before documenting module relationships.
- **Generated output:** exclude `dist/`, `build/`, `generated/`, `.next/`, `out/`, and `__pycache__/` from source conventions.
- **Example environments:** inspect committed example or template environment files for required variable names, never secret values.
- **Dependency roles:** separate production dependencies from development and test tooling.
- **Test TODOs:** classify TODOs under tests as coverage gaps rather than production debt.
- **High-churn files:** use recent history as a fragility signal and label it as such rather than inferring defects.

## Anti-Patterns

| Avoid | Use instead |
|---|---|
| Naming an architecture from directory labels alone | Describe verified directories, imports, and data flow |
| Identifying a framework without checking manifests | Cite the dependency or configuration that proves it |
| Guessing a datastore from variable names | Verify drivers, clients, configuration, or integration code |
| Treating generated output as coding convention | Document maintained source only |

## Scan Output Guide

Use these scan sections during investigation when present:

- `CODE METRICS`: language totals and large-file complexity signals.
- `CI/CD PIPELINES`: detected build and delivery platforms.
- `CONTAINERS & ORCHESTRATION`: container and deployment configuration.
- `SECURITY & COMPLIANCE`: security tooling and policy files.
- `PERFORMANCE & TESTING`: benchmark, profiling, and load-testing markers.

The scan is evidence discovery, not proof of architectural intent. Verify its findings against maintained files before documenting them.