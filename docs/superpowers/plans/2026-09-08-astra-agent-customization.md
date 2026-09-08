# Astra Agent Customization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Separate Codex/Astra and GitHub Copilot guidance, reduce conflicting instructions, and make shared Copilot synchronization deterministic without changing trading behavior.

**Architecture:** Workspace-only Codex guidance lives in `/home/ubuntu/workspace/.agents`; repository Codex guidance lives directly in `ogamiOanda/.agents`; Copilot assets remain under `.github`. A validated manifest synchronizes workspace-owned Copilot files while repository-owned Codex and Copilot files remain independent.

**Tech Stack:** Markdown, POSIX Bash, git, `rg`, `cmp`, `mktemp`, Codex and GitHub Copilot customization formats.

**Spec:** `docs/superpowers/specs/2026-09-08-astra-agent-customization-design.md`

## Global Constraints

- Do not modify production Python, trading behavior, configuration values, runtime state, or fixtures.
- Do not read or print `config/settings.yaml`, account identifiers, tokens, or private endpoints.
- Do not run integration tests, practice acceptance, live entrypoints, or credentialed tools.
- Preserve approval gates for destructive, external, practice, and live operations.
- Keep `ogamiOanda` standalone-safe; its instructions must not require parent files.
- Keep Codex Skills under `.agents` and Copilot assets under `.github`.
- Do not synchronize or modify `BFScalping`.
- The workspace root is not a Git repository. Commit only `ogamiOanda` changes and report workspace changes separately.
- Verify with Bash fixture tests, shell syntax, scoped sync checks, `git diff --check`, and final status.
- Stage explicit paths only; do not stash, reset, or use checkout-based revert.

---

## File Map

**Workspace:** modify `AGENTS.md`, `scripts/sync-agent-customizations.sh`, and selected shared `.github` files; create `.agents/skills/workspace-verification/SKILL.md`, `agent-customizations.manifest`, and `scripts/test-agent-customizations.sh`.

**ogamiOanda:** modify `AGENTS.md`, `.github/copilot-instructions.md`, retained Copilot Skills, and synchronized shared assets; create two `.agents` Skills, a review agent, and generated manifest; delete redundant `.github/AGENTS.md`, instructions, and prompt.

**Command interface:** `scripts/sync-agent-customizations.sh [--check] [--repo NAME]`. Tests override the workspace with `AGENT_CUSTOMIZATIONS_ROOT`.

**Manifest interface:** exactly three tab-separated fields per row: `repository`, source-relative path, destination-relative path. The generated repository manifest contains sorted destination-relative paths.

---

### Task 1: Specify Manifest Synchronization with Failing Fixture Tests

**Files:**
- Create: `/home/ubuntu/workspace/agent-customizations.manifest`
- Create: `/home/ubuntu/workspace/scripts/test-agent-customizations.sh`
- Test: `/home/ubuntu/workspace/scripts/test-agent-customizations.sh`

**Interfaces:**
- Consumes: current synchronization command.
- Produces: executable contract for parsing, checking, copying, stale cleanup, and repository isolation.

- [ ] **Step 1: Create the initial manifest**

Add the current seven shared Copilot mappings for each repository:

```text
# repository	source-relative-path	destination-relative-path
BFScalping	.github/instructions/workspace-code-quality.instructions.md	.github/instructions/workspace-code-quality.instructions.md
BFScalping	.github/instructions/workspace-markdown.instructions.md	.github/instructions/workspace-markdown.instructions.md
BFScalping	.github/instructions/workspace-security.instructions.md	.github/instructions/workspace-security.instructions.md
BFScalping	.github/instructions/workspace-tests.instructions.md	.github/instructions/workspace-tests.instructions.md
BFScalping	.github/prompts/workspace-start-implementation.prompt.md	.github/prompts/workspace-start-implementation.prompt.md
BFScalping	.github/agents/workspace-implementation.agent.md	.github/agents/workspace-implementation.agent.md
BFScalping	.github/skills/workspace-verification/SKILL.md	.github/skills/workspace-verification/SKILL.md
ogamiOanda	.github/instructions/workspace-code-quality.instructions.md	.github/instructions/workspace-code-quality.instructions.md
ogamiOanda	.github/instructions/workspace-markdown.instructions.md	.github/instructions/workspace-markdown.instructions.md
ogamiOanda	.github/instructions/workspace-security.instructions.md	.github/instructions/workspace-security.instructions.md
ogamiOanda	.github/instructions/workspace-tests.instructions.md	.github/instructions/workspace-tests.instructions.md
ogamiOanda	.github/prompts/workspace-start-implementation.prompt.md	.github/prompts/workspace-start-implementation.prompt.md
ogamiOanda	.github/agents/workspace-implementation.agent.md	.github/agents/workspace-implementation.agent.md
ogamiOanda	.github/skills/workspace-verification/SKILL.md	.github/skills/workspace-verification/SKILL.md
```

- [ ] **Step 2: Build a disposable test harness**

Use:

```bash
project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
sync_script="$project_root/scripts/sync-agent-customizations.sh"
fixture_root="$(mktemp -d)"
trap 'rm -rf "$fixture_root"' EXIT
```

Add `expect_success`, `expect_failure`, and `assert_file_content` helpers. Each case uses a fresh fixture, invokes the synchronizer as `AGENT_CUSTOMIZATIONS_ROOT="$fixture_root" "$sync_script" ...`, and prints its name on failure. Do not export the override globally: later structural assertions must inspect the real `project_root` and `project_root/ogamiOanda` trees.

- [ ] **Step 3: Test successful scoped synchronization**

Assert that normal sync copies two manifest-listed files, writes a sorted generated manifest, and makes `--check --repo repo` succeed. Also assert that `other` is untouched and `repo/.agents/skills/repo-owned/SKILL.md` survives.

- [ ] **Step 4: Test validation and drift failures**

Require nonzero exit for changed or missing destinations, stale generated paths, generated-manifest drift, missing sources, malformed field counts, duplicate destinations, unknown `--repo`, absolute paths, and any `..` segment.

- [ ] **Step 5: Test safe stale cleanup**

Place one stale path in the previous generated manifest. After normal sync, assert the stale file is gone and an adjacent unlisted repository-owned file remains.

- [ ] **Step 6: Prove the test is initially red**

Run:

```bash
bash scripts/test-agent-customizations.sh
```

Expected: FAIL because the existing synchronizer lacks the manifest, root override, and `--repo`.

Workspace files cannot be committed because the workspace root is not a Git repository.

---

### Task 2: Implement Manifest-Driven Synchronization

**Files:**
- Modify: `/home/ubuntu/workspace/scripts/sync-agent-customizations.sh`
- Test: `/home/ubuntu/workspace/scripts/test-agent-customizations.sh`
- Create through sync: `ogamiOanda/.agent-customizations.manifest`

**Interfaces:**
- Consumes: Task 1 manifest and tests.
- Produces: no-write `--check` and safe scoped synchronization.

- [ ] **Step 1: Parse options and resolve the testable root**

Support `--check` and `--repo NAME` in either order; reject duplicates, missing values, and unknown arguments with exit 2.

```bash
script_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
workspace_root="${AGENT_CUSTOMIZATIONS_ROOT:-$script_root}"
manifest_path="$workspace_root/agent-customizations.manifest"
```

- [ ] **Step 2: Validate every manifest row before writes**

Ignore comments and blank lines. Require three tab-separated fields, safe non-absolute relative paths, existing source files, existing repository directories, and unique `repository + destination` keys.

```bash
is_safe_relative_path() {
  local path="$1"
  [[ -n "$path" && "$path" != /* && "$path" != "." && "$path" != ".." &&
     "$path" != ../* && "$path" != */../* && "$path" != */.. ]]
}
```

Derive valid repository names from the manifest rather than a hardcoded array.

- [ ] **Step 3: Implement check mode without mutations**

Compare every source/destination with `cmp -s`. Report `missing:`, `out of sync:`, `stale:`, and generated-manifest drift. Return 1 for drift and perform no directory creation, copying, writing, or deletion.

- [ ] **Step 4: Implement safe normal synchronization**

Copy only manifest destinations. Read stale candidates only from the previous generated manifest, validate each again, delete files individually, and remove empty directories only below `.github` or `.agents`. Atomically replace the generated manifest with a temporary sibling plus `mv`. Never use recursive deletion.

- [ ] **Step 5: Run syntax and fixture tests**

```bash
bash -n scripts/sync-agent-customizations.sh
bash -n scripts/test-agent-customizations.sh
bash scripts/test-agent-customizations.sh
```

Expected: all exit 0.

- [ ] **Step 6: Sync only ogamiOanda**

```bash
./scripts/sync-agent-customizations.sh --repo ogamiOanda
./scripts/sync-agent-customizations.sh --check --repo ogamiOanda
```

Expected: both succeed; `BFScalping` remains unchanged.

- [ ] **Step 7: Commit the repository manifest**

From `ogamiOanda`:

```bash
git add .agent-customizations.manifest
git diff --cached --check
git commit -m "build: track shared agent customization manifest"
```

---

### Task 3: Simplify Codex Instructions and Add Curated Skills

**Files:**
- Modify: `/home/ubuntu/workspace/AGENTS.md`
- Create: `/home/ubuntu/workspace/.agents/skills/workspace-verification/SKILL.md`
- Modify: `ogamiOanda/AGENTS.md`
- Delete: `ogamiOanda/.github/AGENTS.md`
- Create: `ogamiOanda/.agents/skills/ogami-verification/SKILL.md`
- Create: `ogamiOanda/.agents/skills/differential-verification/SKILL.md`
- Test: `/home/ubuntu/workspace/scripts/test-agent-customizations.sh`

**Interfaces:**
- Consumes: approved safety boundaries and existing test/migration docs.
- Produces: one standalone repo contract and two non-overlapping repo Skills.

- [ ] **Step 1: Add failing structural assertions**

Require root `AGENTS.md` to contain no parent or `.github` read directives, require deletion of `.github/AGENTS.md`, require both repo Skills, and reject duplicate or over-240-byte Codex descriptions.

```bash
! rg -n '\.github/AGENTS\.md|\.github/copilot-instructions\.md|\.\./AGENTS\.md' "$repo_root/AGENTS.md"
test ! -e "$repo_root/.github/AGENTS.md"
```

- [ ] **Step 2: Rewrite workspace AGENTS.md**

Keep only shared scope, user-authorized autonomy, secrets, destructive/live approval, focused verification, final diff/status, and the distinction between `.agents` and `.github`. Document `sync-agent-customizations.sh --check --repo NAME`.

- [ ] **Step 3: Create the workspace verification router**

It selects the owning repository, reads that root `AGENTS.md`, inspects diff/status, uses repository-specific validation, and never escalates to live or credentialed checks implicitly.

- [ ] **Step 4: Rewrite ogamiOanda AGENTS.md**

State that `src/ogami_oanda` is production source and root modules are compatibility surfaces. Preserve characterization/contract behavior and example-config safety. Pre-authorize focused offline `tests/` pytest. Require explicit authorization for integration, practice acceptance, and live commands. Define completion as implementation, correction of caused failures, relevant verification, and final diff/status.

Route details only when applicable:

```md
- Test commands and external boundaries: `tests/README.md`
- Layer or live-flow changes: `docs/architecture-migration.md`
- Legacy parity or golden traces: `docs/differential-verification.md`
- Migration-state questions: `docs/migration-map.md`
```

- [ ] **Step 5: Create ogami-verification**

Frontmatter:

```yaml
---
name: ogami-verification
description: Verify completed ogamiOanda changes with risk-scaled offline checks; use for explicit verification or before completing trading and migration changes.
---
```

Route to `../../../tests/README.md`. Start with the affected pytest node/file; use Ruff for code changes; reserve the full non-integration suite for broad or high-risk changes. Prohibit integration and live/practice commands without explicit authorization.

- [ ] **Step 6: Create differential-verification**

Frontmatter:

```yaml
---
name: differential-verification
description: Verify ogamiOanda legacy parity, golden traces, intentional deltas, or changes to the differential harness.
---
```

Route to `../../../docs/differential-verification.md`, preserve baseline identity and offline execution, and begin with the affected differential test.

- [ ] **Step 7: Remove redundant .github/AGENTS.md and verify**

```bash
bash /home/ubuntu/workspace/scripts/test-agent-customizations.sh
git diff --check
rg -n '\.github/AGENTS\.md|\.github/copilot-instructions\.md|\.\./AGENTS\.md' AGENTS.md
```

Expected: tests pass, diff check passes, and `rg` returns no matches.

- [ ] **Step 8: Commit repo Codex guidance**

```bash
git add AGENTS.md .agents/skills/ogami-verification/SKILL.md   .agents/skills/differential-verification/SKILL.md .github/AGENTS.md
git commit -m "docs: streamline Codex guidance for Astra"
```

---

### Task 4: Consolidate Copilot Instructions, Prompt, and Agents

**Files:**
- Modify: workspace shared security instruction, implementation agent, implementation prompt, and verification Skill.
- Modify through sync: matching `ogamiOanda/.github` files.
- Modify: `ogamiOanda/.github/copilot-instructions.md`
- Create: `ogamiOanda/.github/agents/code-review.agent.md`
- Delete: redundant review, Markdown, QA, security instructions and old implementation prompt.

**Interfaces:**
- Consumes: Task 2 synchronizer.
- Produces: one instruction per concern and one implementation prompt.

- [ ] **Step 1: Add failing duplicate-removal checks**

Require these files to be absent:

```text
.github/instructions/code-review-generic.instructions.md
.github/instructions/markdown-commonmark.instructions.md
.github/instructions/qa-engineering-best-practices.instructions.md
.github/instructions/secrets-config-security.instructions.md
.github/prompts/start-implementation-as-plan.prompt.md
```

Require exactly one `*start-implementation*.prompt.md` and reject `../../AGENTS.md` or `../../.github` inside Copilot instructions.

- [ ] **Step 2: Consolidate shared policy**

Add the unique config-validation and sanitized-error rules to `workspace-security.instructions.md`. Do not duplicate repository paths or GitHub product procedures. Leave the shared Markdown and test instructions as the sole owners of their concerns.

- [ ] **Step 3: Make the shared implementation agent role-only**

Retain controlling-path discovery, preservation of unrelated changes, completion of requested implementation, and reporting. Remove repeated safety/test/git prose already owned elsewhere.

- [ ] **Step 4: Replace the shared implementation prompt**

Use:

```md
Implement the approved plan to completion. Work through coherent change units, inspect the result, fix failures caused by the work, and run verification proportional to the affected behavior. Continue without routine review stops unless the plan identifies a checkpoint or the next decision changes scope, requires unsafe inference, or has an irreversible or external effect. Preserve unrelated changes and finish with the changed files and verification outcomes.
```

- [ ] **Step 5: Reduce the shared Copilot verification Skill**

Make it a router that selects the repository, reads its verification documentation, inspects diff/status, and runs the narrowest relevant offline check. Do not repeat global safety rules.

- [ ] **Step 6: Sync shared files only to ogamiOanda**

```bash
./scripts/sync-agent-customizations.sh --repo ogamiOanda
./scripts/sync-agent-customizations.sh --check --repo ogamiOanda
```

Expected: both succeed; no BFScalping files change.

- [ ] **Step 7: Make Copilot instructions standalone-safe**

Reference only `../AGENTS.md` and repository-local paths. Retain Copilot-specific entry guidance.

- [ ] **Step 8: Create a review-only Copilot agent**

The agent description must explicitly say code review. Its body produces Japanese findings unless asked otherwise, orders findings by severity, references concrete files/behavior, prioritizes correctness/security/regressions/tests/architecture, and does not apply patches unless requested.

- [ ] **Step 9: Delete overlapping files and verify**

Delete the five paths from Step 1, then run:

```bash
bash /home/ubuntu/workspace/scripts/test-agent-customizations.sh
/home/ubuntu/workspace/scripts/sync-agent-customizations.sh --check --repo ogamiOanda
git diff --check
```

Expected: all exit 0.

- [ ] **Step 10: Commit Copilot consolidation**

```bash
git add .agent-customizations.manifest .github/copilot-instructions.md   .github/agents .github/instructions .github/prompts   .github/skills/workspace-verification/SKILL.md
git diff --cached --name-status
git commit -m "docs: separate and consolidate Copilot guidance"
```

Confirm the staged list contains no production or private file.

---

### Task 5: Narrow Repository-Owned Copilot Skills

**Files:**
- Modify: six `.github/skills/*/SKILL.md` files other than shared workspace verification.
- Create: `.github/skills/acquire-codebase-knowledge/references/workflow.md`
- Preserve: all existing references, assets, templates, and scripts.

**Interfaces:**
- Consumes: existing supporting resources.
- Produces: short root Skills with mutually clear triggers.

- [ ] **Step 1: Add failing trigger assertions**

Require descriptions to express:

- acquire: explicit mapping/documentation/onboarding; exclude routine edits;
- reproduction: reproduction-only/diagnosis-only; exclude fix requests;
- coverage: explicit coverage request or target;
- refactor: explicit plan-only deliverable;
- secret scanning: GitHub configuration, push protection, or alerts;
- security review: explicit source vulnerability audit.

Reject descriptions longer than 320 bytes.

- [ ] **Step 2: Convert acquire-codebase-knowledge to a router**

Keep only trigger, output summary, evidence rule, and references to `workflow.md`, `inquiry-checkpoints.md`, and conditional `stack-detection.md`. Move phases, focus mode, gotchas, anti-patterns, and template catalog into `references/workflow.md`. Do not change `scan.py` or templates.

- [ ] **Step 3: Narrow bug-reproduction-brief**

Keep expected/actual, minimal safe reproduction, evidence, and repeatability. Stop before repair only for a reproduction-only deliverable. When the user requested a fix, establish reproduction and return control to implementation.

- [ ] **Step 4: Replace blanket coverage behavior**

Trigger only on explicit coverage work. Use the requested target, check pytest help for `--cov`, report missing `pytest-cov` without installing it, do not edit `pyproject.toml`, never infer 100 percent, and add tests only for observable behavior.

- [ ] **Step 5: Make refactor-plan plan-only**

Remove the unconditional confirmation stop. Activate only for a plan-only request and do not add a second approval gate unless the user requested one.

- [ ] **Step 6: Separate security Skills**

`secret-scanning` owns GitHub secret-scanning settings, push protection, custom patterns, blocked pushes, and alert remediation. `security-review` owns explicit source vulnerability audits and uses the requested scope. Neither claims the other's workflow. Detailed procedures remain in existing references.

- [ ] **Step 7: Verify resources and triggers**

```bash
bash /home/ubuntu/workspace/scripts/test-agent-customizations.sh
find .github/skills \( -path '*/references/*' -o -path '*/assets/*' -o -path '*/scripts/*' \) -type f | sort
git diff --check
```

Expected: structural tests pass and all supporting files remain.

- [ ] **Step 8: Commit Skill cleanup**

```bash
git add .github/skills/acquire-codebase-knowledge/SKILL.md   .github/skills/acquire-codebase-knowledge/references/workflow.md   .github/skills/bug-reproduction-brief/SKILL.md   .github/skills/pytest-coverage/SKILL.md   .github/skills/refactor-plan/SKILL.md   .github/skills/secret-scanning/SKILL.md   .github/skills/security-review/SKILL.md
git commit -m "docs: narrow Copilot skill activation boundaries"
```

---

### Task 6: Final Verification and Handoff

**Files:**
- Modify only customization Markdown/Bash if checks reveal defects.
- Do not modify `src`, Python tests, config values, or runtime files.

**Interfaces:**
- Consumes: Tasks 1–5.
- Produces: verified dual-harness customization and an explicit workspace handoff.

- [ ] **Step 1: Run workspace checks**

```bash
bash -n /home/ubuntu/workspace/scripts/sync-agent-customizations.sh
bash -n /home/ubuntu/workspace/scripts/test-agent-customizations.sh
bash /home/ubuntu/workspace/scripts/test-agent-customizations.sh
```

Expected: all exit 0.

- [ ] **Step 2: Check scoped synchronization**

```bash
/home/ubuntu/workspace/scripts/sync-agent-customizations.sh --check --repo ogamiOanda
```

Expected: exit 0. Do not run unfiltered synchronization.

Run the BFScalping check only to record expected drift:

```bash
/home/ubuntu/workspace/scripts/sync-agent-customizations.sh --check --repo BFScalping
```

A nonzero result is an acknowledged follow-up; do not repair it.

- [ ] **Step 3: Verify discovery counts and obsolete-file removal**

```bash
test "$(find /home/ubuntu/workspace/.agents/skills -name SKILL.md | wc -l)" -eq 1
test "$(find .agents/skills -name SKILL.md | wc -l)" -eq 2
test ! -e .github/AGENTS.md
test ! -e .github/prompts/start-implementation-as-plan.prompt.md
test ! -e .github/instructions/code-review-generic.instructions.md
test ! -e .github/instructions/markdown-commonmark.instructions.md
test ! -e .github/instructions/qa-engineering-best-practices.instructions.md
test ! -e .github/instructions/secrets-config-security.instructions.md
```

Expected: exit 0.

- [ ] **Step 4: Inspect repository boundaries**

```bash
git status --short
git diff --check
git diff --stat
git diff -- AGENTS.md .agents .github .agent-customizations.manifest docs/superpowers
git diff --name-only -- config/settings.yaml runtime src
```

Expected: no whitespace errors; the final command prints nothing; no private data appears.

- [ ] **Step 5: Record intentionally skipped tests**

Do not run pytest, integration, practice acceptance, or live commands. Record that only Markdown and Bash customization infrastructure changed and the dedicated Bash fixture suite passed.

- [ ] **Step 6: Commit corrections only when needed**

If verification changes files, stage only those customization paths and commit:

```bash
git commit -m "test: verify agent customization layout"
```

Do not create an empty commit.

- [ ] **Step 7: Prepare the final handoff**

List workspace-root files changed, repository commits, exact verification results, deliberate BFScalping non-synchronization, skipped production/credentialed tests, and the future option of moving workspace assets into a dedicated configuration repository.
