# Public Release Plan

## Purpose

This document defines how to derive a clean public repository from the current
private Agent Context Engine working repository without carrying over private history,
local operating context, or runtime data.

The goal is:

- keep the current private repository as the full internal source of truth
- create a curated public copy with a fresh Git history
- preserve the current code and documentation content wherever it is fit for
  public use
- make architecture, installation, storage, control surfaces, and data flows
  easier to understand for external users

## Release Strategy

Use a **copy-and-curate** release flow, not an in-place public flip.

Recommended process:

1. Freeze the private repository as the internal origin.
2. Copy the repository into a new target folder for the public project.
3. Remove excluded paths and sanitize retained paths.
4. Rewrite the public-facing docs in English.
5. Initialize a new Git repository in the public folder.
6. Create a first commit such as `Initial public release`.
7. Connect that new repository to the public GitHub remote.

This preserves the current file contents while intentionally dropping the
private Git history.

## Public Repository Origin Note

The public repository should explicitly state that it is a curated public
derivative of a longer-running private development repository.

Recommended wording:

> This repository is the public, curated release of Agent Context Engine. It was
> derived from a longer-running private development repository, but starts with
> a fresh public history to avoid publishing private runtime artifacts,
> operator context, and internal development traces.

Add this note to:

- `README.md`
- optionally `docs/project-origin.md`

Do not include:

- private file paths
- references to private-only repos
- references to local machine layout

## Public Product Contract

The public repository should present Agent Context Engine as:

- a local-first runtime memory layer for coding agents
- a cross-harness context engine
- a system for capture, retrieval, summarization, dreaming, graph enrichment,
  and safety review
- an inspectable and controllable local runtime

The public contract should be written from the perspective of:

- a new external user
- a maintainer
- an integrator

It should not assume prior knowledge of the internal brownfield refactor
history.

## What To Keep

These paths are strong candidates for the public repository:

- `backend/`
- `frontend/`
- `scripts/`
- `templates/`
- `contracts/`
- `README.md`
- `LICENSE`
- `SECURITY.md`
- `CONTRIBUTING.md`
- `AGENT_BOOTSTRAP.md`
- `session-start-hook-entry.md`
- selected `docs/architecture/*`
- selected `docs/setup/*`
- selected `docs/runbooks/*`
- selected `docs/decisions/*`
- selected `docs/epics/*`

Keep the code-near `.spec.md` files. They are useful public boundary
documentation and help explain the system without forcing readers into internal
progress logs.

## What To Remove Entirely

These paths should not be copied into the public repository in their current
form:

- `memory/`
- `docs/knowledge/`
- `refactor-backup/`
- `test-agent-memory/`
- `.codex/`
- `.codex-runtime/`
- `.claude/`
- `.cursor/`
- `.agents/`
- `.gemini/`
- `.opencode/`
- `.idea/`
- `frontend/dist/`
- local caches and `__pycache__/`
- `.DS_Store`

These are private, runtime, machine-local, or operator-local artifacts.

## What To Rework Before Publishing

These paths likely belong in the public repository, but need structural or
language cleanup first:

- `AGENTS.md`
- `README.md`
- `docs/index.md`
- `docs/product/README.md`
- `docs/architecture/SYSTEM_OVERVIEW.md`
- `docs/architecture/DOMAIN_MODEL.md`
- `docs/setup/BUILD_AND_CHECKS.md`
- `docs/setup/RUNNER_HARNESSES.md`
- `docs/runbooks/integration-management.md`
- `docs/runbooks/monitor-operator-workflows.md`
- `frontend/src/features/integrations/IntegrationsPanel.tsx`
- `frontend/src/features/personal/PersonalPanel.tsx`
- installer/help text in `backend/src/agent_context_engine/interfaces/cli/commands/installation.py`
- hook startup guidance in `backend/src/agent_context_engine/interfaces/hooks/support/session_context.py`

Primary rework themes:

- English only
- remove local machine paths
- remove references to private repos
- remove references to internal-only workflows
- reduce brownfield narration
- clarify public behavior vs internal implementation notes

## What To Archive Or Rehome Internally

The following content is valuable, but should remain private or move into a
separate maintainer-only area, not the public product repo:

- most of `docs/progress/`
- most of `docs/archive/`
- `docs/research/`
- internal refactor execution plans
- rollback/restore instructions tied to private backups
- local operator habits and private workflows
- private repo maps and working context

If parts of these are still useful publicly, extract a clean summary rather than
copying the original files.

## Documentation Language Policy

The public repository should use English as the default and normative language.

Rules:

- all top-level product docs in English
- all setup and operator docs in English
- all architecture docs in English
- all README-like files in English
- public monitor copy may stay multilingual in the UI if desired, but docs
  should not switch between German and English arbitrarily

Private/internal-only notes can remain in German in the private origin repo.

## Documentation Restructure For The Public Repo

The current docs tree mixes:

- product entrypoints
- active architecture references
- internal progress history
- operator notes
- private knowledge

The public repository should be reorganized into a smaller, clearer contract.

Recommended public docs structure:

- `README.md`
- `docs/overview.md`
- `docs/architecture/system-overview.md`
- `docs/architecture/data-flow.md`
- `docs/architecture/storage-model.md`
- `docs/architecture/safety-model.md`
- `docs/architecture/monitor.md`
- `docs/setup/installation.md`
- `docs/setup/harnesses.md`
- `docs/setup/build-and-checks.md`
- `docs/operator/control-surfaces.md`
- `docs/operator/troubleshooting.md`
- `docs/project-origin.md`
- `docs/decisions/`
- code-near `.spec.md` files

Recommended internal-only structure in the private origin repo:

- `docs/progress/`
- `docs/archive/`
- `docs/research/`
- private repo maps
- private rollback and recovery procedures

## Runtime Knowledge Path Change

For the public repository, `docs/knowledge/` should no longer be the runtime
knowledge location.

Recommended change:

- move runtime-managed knowledge to `memory/knowledge/`
- treat it as local runtime state
- keep it out of Git

Why:

- `docs/knowledge/` looks like versioned product documentation
- the actual content is user-local runtime context
- `memory/knowledge/` better matches the repository privacy model
- it aligns with the existing rule that runtime data lives under `memory/`

Recommended public behavior:

- installer creates `memory/knowledge/` on demand
- repo/project index lives under `memory/knowledge/repos.md`
- personal memory remains under `memory/personal/`
- docs refer to the runtime knowledge path as local state, not source docs

Migration note:

- private repo may keep compatibility for reading legacy `docs/knowledge/repos.md`
- public repo should prefer `memory/knowledge/repos.md`
- if backward compatibility is needed, do it through a migration or fallback
  reader, not through versioning the runtime file

## Storage, Data Paths, And Control Surfaces

The public repository must make the following easy to understand:

### Storage layers

- SQLite as the operational source of truth
- `memory/` as runtime filesystem state
- optional graph artifacts and optional Neo4j projection
- frontend build output as a derived artifact, not primary state

### Data paths

- hook payload -> normalization -> SQLite/event persistence
- scheduler -> summaries/dreams/graph stages
- retrieval -> filtering -> result/audit logging
- monitor -> read-only inspection and bounded control actions

### Control surfaces

- CLI commands
- wrapper commands
- hook entrypoints
- monitor/API
- user-only approval controls

### Safety boundaries

- deterministic gates before optional LLM expansion where possible
- explicit risk review and override model
- auditability for actions and exceptions
- runtime-local data boundaries

These concerns should become first-class public docs, not details hidden only
inside progress notes.

## Activation Model Must Be Simplified

One of the largest public product risks is activation confusion.

External users should not need to infer when Agent Context Engine is active from a mix
of wrappers, hook configs, and installation side effects.

The public repository should explicitly define three activation modes:

### 1. Single-project mode

This should be the default and recommended path for most users.

Behavior:

- the user installs Agent Context Engine directly into the project they actively work in
- hook-based clients such as Codex and Claude can use the project-local setup
  directly from that root
- no wrapper command is required for the normal case

This should be presented as the simplest way to get started.

### 2. Central-installation mode

This is the advanced multi-project path.

Behavior:

- the user keeps one central Agent Context Engine root
- one or more external workspaces are connected to that root
- project activation or external workspace hook setup is used where needed

This should be documented as a power-user or multi-repository workflow, not as
the primary mental model for new users.

### 3. Wrapper mode

Wrapper commands should be documented as an explicit activation path, not as the
default explanation for the whole system.

Behavior:

- wrappers start the client in a way that ensures the central Agent Context Engine root
  is active
- wrappers are useful when the user wants one shared installation across many
  repositories
- wrappers are also useful for clients that need startup from the Agent Context Engine
  root or need plugin/global bridge behavior

Public documentation should explain wrappers as:

- optional for Codex and Claude in the single-project case
- useful for central multi-project setups
- primary only for clients whose integration model depends on central startup

## Default Public Narrative

The public docs should lead with:

- `single-project mode` as the easiest and most intuitive setup
- `central-installation mode` as the advanced shared-memory setup
- `wrapper mode` as an implementation/activation option, not the first concept
  users must understand

This matters especially for:

- `codex`
- `claude`

If Agent Context Engine is installed directly in the root where the user works, the
normal experience should be described as:

- start the client normally from that root
- project-local hooks apply directly
- Agent Context Engine is active without requiring a wrapper command

## Public Documentation Requirements For Activation

The public repository should contain dedicated setup documentation for:

- when Agent Context Engine becomes active
- which clients work directly from the current project root
- which clients require project activation
- which clients use wrappers as the primary path
- when a wrapper is optional versus required

Recommended public docs:

- `docs/setup/activation-model.md`
- `docs/setup/single-project-mode.md`
- `docs/setup/central-installation-mode.md`

The README should include a short decision guide such as:

- `I want Agent Context Engine only in this repo` -> use single-project mode
- `I want one shared memory root for several repos` -> use central-installation mode
- `I want to launch from anywhere with a shared root` -> use wrappers

## Public Readability Requirements

A new external reader should be able to answer these questions quickly:

1. What does the system do?
2. What is stored?
3. Where is it stored?
4. What is local runtime data versus versioned source?
5. How do hooks, CLI, scheduler, monitor, and retrieval interact?
6. Which harnesses are supported?
7. When does Agent Context Engine become active, and do I need wrappers?
8. What can the monitor control, and what remains outside the monitor?
9. What are the privacy and safety boundaries?

If those answers require reading internal progress logs, the public repository
is still too private in shape.

## Code And Product Cleanup Checklist

Before publishing, fix these classes of issues:

- hardcoded local fallback paths
- private repo references
- German-only public docs
- internal progress language in user-facing docs
- `latest` frontend dependency ranges
- stale backup files such as `.bak`
- committed generated local bundles or snapshots
- runtime test fixtures that include local paths or session-like data

## Suggested Export Inventory

Use this four-way decision model for every path:

- `keep`
- `sanitize`
- `exclude`
- `rehome-in-private-origin`

Suggested initial classification:

### Keep

- `backend/`
- `frontend/`
- `scripts/`
- `templates/`
- `contracts/`
- `LICENSE`
- `SECURITY.md`
- `CONTRIBUTING.md`

### Sanitize

- `README.md`
- `AGENTS.md`
- `AGENT_BOOTSTRAP.md`
- `session-start-hook-entry.md`
- `docs/index.md`
- `docs/product/README.md`
- `docs/architecture/*`
- `docs/setup/*`
- `docs/runbooks/*`
- `docs/decisions/*`
- `docs/epics/*`

### Exclude

- `memory/`
- `docs/knowledge/`
- `docs/archive/`
- `docs/research/`
- most of `docs/progress/`
- `refactor-backup/`
- `test-agent-memory/`

### Rehome In Private Origin

- detailed progress and handover logs
- private repo maps
- restore/rollback notes tied to local artifacts
- private operator workflows

## First Public Commit Scope

The first public commit should be intentionally small and coherent.

Recommended scope:

- public-ready code
- public-ready setup docs
- public-ready architecture docs
- public-ready safety docs
- public-ready origin note

Avoid shipping:

- historical documentation dumps
- internal migration archaeology
- experimental side areas that are not needed for first use

## Acceptance Criteria For Public Readiness

The new public repository is ready when:

- it has a fresh Git history
- no private runtime data is tracked
- all public docs are in English
- runtime knowledge lives under `memory/knowledge/` instead of `docs/knowledge/`
- no absolute personal machine paths remain in public-facing code or docs
- a fresh clone can install and run the documented basic flow
- architecture, storage, data flow, and control surfaces are understandable
  without internal handover documents
- the repository clearly explains what is public product behavior versus local
  runtime state

## Recommended Next Execution Steps

1. Create a full path-by-path export inventory.
2. Define the target public docs tree.
3. Move runtime knowledge handling to `memory/knowledge/`.
4. Sanitize installation, bootstrap, and integration docs.
5. Remove test/runtime/private artifacts from the public copy.
6. Rewrite the public README and architecture entrypoints in English.
7. Initialize the public repository with a fresh Git history.
