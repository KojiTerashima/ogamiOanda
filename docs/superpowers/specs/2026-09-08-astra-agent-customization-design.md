# Astra Agent Customization Design

## Goal

Make the `/home/ubuntu/workspace` and `ogamiOanda` agent guidance efficient for GPT-6 Astra while preserving GitHub Copilot support and all existing trading, credential, and external-mutation safety boundaries.

## Scope

This change reorganizes durable agent instructions and their synchronization. It does not modify trading behavior, production Python code, credentials, runtime state, test fixtures, or live-operation commands.

The implementation covers:

- concise workspace and repository `AGENTS.md` files for Codex;
- a small set of Codex skills under `.agents/skills`;
- separate GitHub Copilot instructions, prompts, agents, and skills under `.github`;
- consolidation of overlapping Copilot instructions and prompts;
- narrower trigger and stop conditions in retained Copilot skills;
- manifest-driven synchronization of shared assets;
- deterministic structural checks for the customization layout.

## Design Principles

1. Always-loaded instructions contain only durable scope, safety, authority, and completion rules.
2. Task-specific procedures use progressive disclosure through a skill, reference, or existing project document.
3. Codex and GitHub Copilot use separate discovery locations and may receive different wording for the same project policy.
4. Explicit user requests control task scope. Optional skills must not introduce a review stop when the user already requested implementation.
5. Offline, reversible verification is pre-authorized. Credentialed integration, practice mutation, live trading, destructive actions, and external publication remain approval-gated.
6. Verification effort is proportional to change risk. Small documentation edits do not trigger the full offline suite; trading and migration changes retain focused contract and boundary verification.
7. Shared and repository-owned files have explicit ownership so synchronization never overwrites unrelated repository customization.

## Alternatives Considered

### Separate Codex and Copilot trees with manifest synchronization

Selected. Workspace-owned Codex assets live under `.agents`; workspace-owned Copilot assets live under `.github`. A manifest lists each shared source and repository destination. This is portable, explicit, and allows each harness to receive only relevant instructions.

### Generate both formats from a neutral template tree

Rejected for now. It would reduce repeated policy text but introduces a template language and generator that are disproportionate to the current number of shared files.

### Symlink `.agents/skills` to `.github/skills`

Rejected. It exposes broad Copilot skills to Astra, prevents harness-specific trigger wording, and creates portability problems for Windows and standalone clones.

## Target Layout

```text
/home/ubuntu/workspace/
├── AGENTS.md
├── .agents/
│   └── skills/
│       └── workspace-verification/
│           └── SKILL.md
├── .github/
│   ├── copilot-instructions.md
│   ├── instructions/
│   ├── prompts/
│   ├── agents/
│   └── skills/
├── agent-customizations.manifest
├── scripts/
│   ├── sync-agent-customizations.sh
│   └── test-agent-customizations.sh
└── ogamiOanda/
    ├── AGENTS.md
    ├── .agents/
    │   └── skills/
    │       ├── ogami-verification/
    │       │   └── SKILL.md
    │       └── differential-verification/
    │           └── SKILL.md
    └── .github/
        ├── copilot-instructions.md
        ├── instructions/
        ├── prompts/
        ├── agents/
        └── skills/
```

The workspace root is not currently a Git repository. Workspace files remain the local shared source; repository copies and this design are versioned in `ogamiOanda`. Creating a parent Git repository or a separate configuration repository is outside this change because nested repositories make that a separate ownership decision.

## Instruction Architecture

### Workspace `AGENTS.md`

The workspace file contains only rules that apply to both `BFScalping` and `ogamiOanda`:

- precedence and repository-boundary behavior;
- protection of secrets and account data;
- approval gates for destructive and live-trading operations;
- autonomy for reversible work already authorized by the user;
- risk-proportional validation and final diff/status inspection;
- a clear statement that `.agents` is for Codex and `.github` is for Copilot.

It does not require Codex to read Copilot files or enumerate every available customization file.

### `ogamiOanda/AGENTS.md`

The repository file is self-contained so it also works in a standalone clone. It does not instruct Codex to read `.github/AGENTS.md`, `.github/copilot-instructions.md`, or a parent workspace file.

It defines:

- `src/ogami_oanda` as the production source and root modules as compatibility surfaces;
- characterization and contract preservation;
- safe configuration files and secret handling;
- autonomous use of focused offline tests;
- approval gates for integration, practice mutation, and live commands;
- completion criteria for implementation requests;
- on-demand routes to `tests/README.md`, `docs/architecture-migration.md`, `docs/differential-verification.md`, and `docs/migration-map.md`.

`.github/AGENTS.md` is removed after its unique repository rules are folded into the root file.

### Copilot instructions

`ogamiOanda/.github/copilot-instructions.md` becomes standalone-safe and links only to files inside the repository. It does not refer to `../../.github` or `../../AGENTS.md`.

Path instructions are consolidated so a file does not receive two instructions expressing the same rule:

- retain one test instruction;
- retain one Markdown instruction;
- retain one secret/config instruction;
- retain focused instructions for documentation synchronization, self-explanatory comments, and excluding prompt meta-commentary;
- move generic review behavior from an `applyTo: "**"` instruction into a review-specific agent or prompt.

## Codex Skills

Only three small Codex skills are introduced.

### Workspace verification

Available when Codex starts from the workspace root. It selects the owning repository, reads that repository's `AGENTS.md`, checks the changed-file list and diff, then delegates verification details to the repository guidance.

### ogami verification

Available inside `ogamiOanda`. Its description triggers only when the user asks to verify work or when an implementation affecting trading or migration behavior is ready for completion. The body routes to `tests/README.md`, selects the narrowest offline command, and prohibits implicit escalation to integration or live operations.

### Differential verification

Triggers only for legacy parity, golden traces, intentional deltas, or the differential harness. It routes to `docs/differential-verification.md` and does not preload that document for ordinary changes.

Each `SKILL.md` remains a short router. Existing documentation owns detailed commands and domain explanation.

## Copilot Skill Changes

The Copilot skill collection remains under `.github/skills`, but its activation boundaries are tightened:

- `refactor-plan` becomes plan-only and does not stop an explicit implementation request;
- `pytest-coverage` runs only for an explicit coverage request, uses a user-supplied target, and does not require 100 percent coverage by default;
- `bug-reproduction-brief` triggers only for reproduction-only or diagnosis-only requests;
- `security-review` triggers only for an explicit security audit and scans the requested scope rather than the entire repository by default;
- `secret-scanning` covers GitHub secret-scanning configuration and alert workflows, not general source security review;
- `acquire-codebase-knowledge` becomes a concise router; its phase details, templates, and checklists stay in supporting files;
- `workspace-verification` retains risk-proportional checks and no longer repeats general repository guidance.

Detailed security, scanning, and documentation material remains in `references`, `assets`, and `scripts` and is loaded only when the selected workflow needs it.

## Prompt and Agent Changes

The two implementation prompts are replaced by one prompt. It defines completion as implementation, inspection, correction of failures caused by the work, and proportionate verification. It does not require a validation cycle after every plan step.

The shared implementation agent keeps only role-specific behavior. Repository safety and test rules remain in repository instructions instead of being duplicated in the agent body. A review-specific Copilot agent owns severity-ordered review output.

## Synchronization Contract

`agent-customizations.manifest` is a line-oriented UTF-8 file. Each non-empty, non-comment line has three tab-separated fields:

```text
repository\tsource-relative-path\tdestination-relative-path
```

Example:

```text
ogamiOanda\t.github/instructions/workspace-code-quality.instructions.md\t.github/instructions/workspace-code-quality.instructions.md
```

The synchronization script:

1. accepts `--check` and an optional `--repo NAME` filter;
2. rejects unknown repositories, absolute paths, `..` path traversal, duplicate destinations, missing sources, and malformed rows;
3. copies only manifest-listed files;
4. writes the active destination list to `<repository>/.agent-customizations.manifest`;
5. removes only stale files listed in the previous generated manifest and never removes unlisted repository-owned files;
6. removes empty generated directories only within `.agents` and `.github`;
7. reports content drift, missing files, stale generated files, and generated-manifest drift in `--check` mode;
8. supports `--repo ogamiOanda` so this change can be applied without modifying `BFScalping`.

The initial manifest preserves the existing BFScalping mappings without synchronizing that repository during this implementation. `ogamiOanda` receives both shared Copilot assets and the selected Codex assets.

## Failure Handling

- Manifest validation fails before any destination mutation.
- A failed copy leaves the previous generated manifest unchanged.
- Stale deletion is restricted to paths recorded by the previous generated manifest.
- Repository-owned files that are absent from the generated manifest are never deleted or overwritten unless they become an explicit destination in the source manifest.
- Sync output names paths but never reads or prints secret configuration.
- The implementation does not invoke integration tests, live entrypoints, practice acceptance, or credentialed tools.

## Verification

A deterministic shell test creates temporary workspace and repository fixtures, invokes the synchronization script against an overridable workspace root, and verifies:

- correct copies for both `.agents` and `.github` destinations;
- `--check` success when synchronized;
- drift, missing source, malformed row, duplicate destination, unknown repository, and traversal rejection;
- stale generated-file detection and removal;
- preservation of repository-owned files;
- `--repo` isolation.

Static checks also verify:

- repository `AGENTS.md` does not require reading Copilot or parent files;
- all Codex skills have concise unique descriptions;
- retained Copilot skills contain the new activation boundaries;
- duplicate implementation prompts and `.github/AGENTS.md` are absent;
- no tracked customization contains credentials or values from `config/settings.yaml`.

The existing `ogamiOanda` offline suite is not required because no production Python behavior changes. Run `git diff --check`, the customization fixture test, shell syntax checks, and `./scripts/sync-agent-customizations.sh --check --repo ogamiOanda` after synchronization.

## Rollout

1. Add the manifest and deterministic synchronization tests without changing current destinations.
2. Update the synchronization script and prove compatibility with the current shared asset set.
3. Simplify workspace and repository `AGENTS.md` files.
4. Add and synchronize the curated Codex skills.
5. Consolidate Copilot instructions, prompts, agents, and skill triggers.
6. Synchronize only `ogamiOanda`, run structural verification, and inspect the exact diff.
7. Leave `BFScalping` unchanged; synchronize it only in a separate reviewed change.

## Out of Scope

- Changes to trading, order, position, candle, backtest, migration, or recovery code.
- Credentialed OANDA checks, practice mutations, or live trading.
- Installation of plugins, MCP servers, or new Python dependencies.
- A generated neutral-template system.
- Initializing a Git repository at `/home/ubuntu/workspace`.
- Synchronizing or modifying `BFScalping` during this implementation.
- Changing personal `~/.codex` configuration or model defaults.
