# Epic: Public Repository Curation And Agent-First Release

## Date

2026-06-18

## Status

Planned

## Objective

Turn the current private Agent Memory repository into a **curated public
repository** with a **fresh Git history**, while keeping the original private
repository intact.

The public repository must remain:

- fully usable as the main product repository
- agent-first and largely agent-operable
- understandable to external users without internal context
- explicit about activation, storage, control surfaces, and safety boundaries
- English-first in documentation, while still supporting German in runtime/UI
  flows where already supported

The public derivative will be prepared in a copied working directory and only
initialized as a new Git repository after the curation work is complete.

## Source And Target Model

### Private origin

- canonical internal working repository
- keeps full historical evolution, progress logs, refactor notes, private repo
  maps, and local operator context
- remains unchanged

### Public derivative

- curated copy derived from the private origin
- starts with a fresh public Git history
- excludes private runtime data, local operating context, and private archive
  material
- becomes the public-facing repository and public distribution vehicle

## Product Decisions

These decisions are fixed for this epic unless explicitly revised later.

1. The public repository starts from a copied working tree, not from the
   current Git history.
2. The original private repository remains the internal source of truth.
3. The public repository is not a reduced technical core. It should remain the
   full primary product repository.
4. The public repository must stay **agent-first**:
   - an agent should be able to install, configure, explain, and operate the
     system end to end
   - except for explicit security/approval decisions that must stay user-owned
5. Users should not need to know or use CLI commands, but CLI must remain
   available and documented.
6. Public documentation is **English by default**.
7. German remains supported where the product already supports it, especially
   through runtime/UI behavior and install-time language choice.
8. The public repository must explain **all major subsystems**, not only a
   reduced subset:
   - hooks
   - wrappers
   - monitor
   - retrieval
   - dreaming
   - graph
   - risk/firewall
   - personal/knowledge
9. Public progress and design context may be retained selectively, but should
   be **condensed and public-safe**, not copied as raw internal history.
10. The public repository should explicitly state that it is a curated public
    derivative of a private development repository.
11. The maintainer identity remains visible in the monitor and README:
    - name
    - LinkedIn reference
12. The first public release should be positioned as:
    - experimental
    - early public release
    - serious and usable, but not over-claiming long-term stability

## Why This Epic Exists

The repository is already strong in functionality, but not yet shaped like a
public product repository.

Current strengths:

- rich local runtime model
- strong agent workflow integration
- monitor/read-model visibility
- retrieval, dreaming, graph, and safety layers
- installation and multi-client support

Current public-readiness gaps:

- private runtime and local operator context are mixed into the repository
- the activation model is too implicit and confusing for new users
- product docs, internal progress docs, and private context docs are mixed
- many public-facing docs still assume internal context or brownfield knowledge
- public explanations of storage, data paths, and control surfaces are not yet
  cut to an external audience

This epic turns the current repository from a strong internal system into a
strong external product repository.

## Success Criteria

The public repository is ready when all of the following are true:

- a fresh public repository can be created from the curated copy
- no private runtime data or local repository maps are tracked
- `docs/knowledge/` is no longer used as the runtime knowledge location
- runtime knowledge is moved to `memory/knowledge/`
- the README is strong by normal public open-source project standards
- public docs are English-first and coherent
- agent-first installation and usage are clearly documented
- users can understand when Agent Memory becomes active
- root/local setup and wrapper-based setup are both clearly explained
- users can understand storage, data flow, layers, and control surfaces without
  reading internal progress notes
- all main product areas remain documented:
  - hooks
  - wrappers
  - monitor
  - retrieval
  - dreaming
  - graph
  - risk/firewall
  - personal/knowledge
- the public repository clearly explains that it is experimental
- the public repository includes a public-safe origin note

## Non-Goals

This epic does not aim to:

- preserve the private Git history in public
- keep every internal progress or research note unchanged
- expose private repo maps or local machine context
- turn the project into a cloud/SaaS product
- remove the existing CLI
- remove German support from runtime/UI where it already exists
- reduce the product surface to only one or two subsystems

## Scope

### In Scope

- public repo curation in the copied working tree
- removal of private/runtime/local artifacts from the public derivative
- English-first rewrite of public-facing docs
- public-safe architecture and setup documentation
- activation model rewrite
- migration of runtime repo knowledge from `docs/knowledge/` to
  `memory/knowledge/`
- public documentation for:
  - installation
  - activation
  - wrappers
  - monitor
  - storage
  - data paths
  - control surfaces
  - safety model
- public-safe condensation of useful progress/epic/design material
- origin note and public positioning

### Out Of Scope

- final product name selection
- final public Git initialization
- final public GitHub push
- removal of maintainer identity from monitor/README
- removing existing major runtime capabilities

## Primary User Experience Goal

An external user or agent should be able to understand the system in this order:

1. what Agent Memory is
2. when it becomes active
3. whether they need wrappers
4. where data is stored
5. what is versioned source versus local runtime
6. how to install it
7. how to operate it
8. how safety and approvals work
9. how to inspect what happened

The product should feel understandable, inspectable, and controllable.

## Activation Model Requirements

The public repository must explicitly explain **when Agent Memory is active**.

This is one of the highest-priority public usability concerns.

### Activation modes

The public docs must describe three explicit activation modes:

#### 1. Project-root mode

The user installs Agent Memory directly into the project root they actively work
in.

Expected behavior:

- normal client startup from that root is enough for supported hook-based flows
- no wrapper command is required in the common case
- this should feel natural for users of Codex and Claude

#### 2. Central-installation mode

The user keeps one central Agent Memory root and connects additional projects to
it.

Expected behavior:

- this is the shared, multi-project operating model
- suitable for users who want one memory runtime across repositories
- requires clearer explanation of external workspace activation

#### 3. Wrapper mode

Wrappers are an explicit startup path, not the only activation explanation.

Expected behavior:

- wrappers are a valid first-class path
- wrappers are especially useful for shared/central setups
- wrappers may be primary for clients whose integration model depends on root
  startup or central plugin/bridge behavior

### Public narrative rule

The docs must present:

- root/project installation and wrapper-based startup as **equal valid entry
  paths**
- the exact activation behavior per client
- wrapper-required versus wrapper-optional clearly

### Client coverage

The activation and support model must explicitly cover:

- `codex`
- `claude`
- `cursor`
- `gemini`
- `opencode`
- `antigravity`

## Documentation Strategy

The public repository must become easier for both humans and agents to navigate.

### Documentation principles

1. English-first public documentation
2. agent-friendly structure and language
3. explicit runtime/source boundaries
4. explicit activation rules
5. explicit storage and data-flow explanations
6. condensed carry-over of useful epics/history instead of raw internal logs

### README requirements

The public `README.md` must become the main external product entrypoint.

It should be strong by normal public repository standards and include:

- short product definition
- why this project exists
- key capabilities
- activation model overview
- installation decision guide
- quickstart
- supported clients
- storage and privacy summary
- control/safety summary
- public origin note
- maintainer identity

### Recommended public docs tree

- `README.md`
- `docs/overview.md`
- `docs/project-origin.md`
- `docs/setup/installation.md`
- `docs/setup/activation-model.md`
- `docs/setup/root-mode.md`
- `docs/setup/central-installation-mode.md`
- `docs/setup/harnesses.md`
- `docs/setup/build-and-checks.md`
- `docs/architecture/system-overview.md`
- `docs/architecture/data-flow.md`
- `docs/architecture/storage-model.md`
- `docs/architecture/safety-model.md`
- `docs/architecture/monitor.md`
- `docs/operator/control-surfaces.md`
- `docs/operator/troubleshooting.md`
- selected `docs/decisions/`
- code-near `.spec.md`

### Progress/epic carry-over policy

Useful internal progress material may be retained in public only if:

- translated to English where needed
- condensed
- stripped of private operating detail
- reframed as architecture/design/roadmap context

The public repository should not become an archaeology dump.

## Runtime Knowledge Path Migration

The public repository should stop using `docs/knowledge/` as runtime storage.

### Required change

Move runtime repo knowledge to:

- `memory/knowledge/repos.md`

### Rationale

- `docs/knowledge` looks like versioned product docs
- runtime repo maps are local user state
- runtime state belongs under `memory/`
- the new path better matches privacy and Git boundaries

### Compatibility expectation

If compatibility is needed, support reading legacy `docs/knowledge/repos.md`
temporarily through migration or fallback logic, but the public contract should
point to `memory/knowledge/repos.md`.

## Storage And Data-Path Documentation Requirements

The public repository must clearly explain:

### Storage layers

- SQLite as the main operational persistence layer
- `memory/` as local runtime filesystem state
- optional graph artifacts
- optional Neo4j projection
- frontend build output as derived artifact

### Data paths

- hook payload -> normalization -> persistence
- persistence -> scheduler -> summary/dream/graph processing
- retrieval -> filtering -> access logging
- monitor -> read-model inspection and bounded control actions

### Control surfaces

- project-local hooks
- wrappers
- CLI
- monitor/API
- user-only approval controls

### Safety boundaries

- deterministic baselines where possible
- risk review and firewall model
- explicit approvals and overrides
- runtime-local privacy boundaries

## Public Repository Content Policy

### Keep

Strong keep candidates:

- `backend/`
- `frontend/`
- `scripts/`
- `templates/`
- `contracts/`
- `LICENSE`
- `SECURITY.md`
- `CONTRIBUTING.md`
- public-safe architecture/setup docs
- code-near specs

### Sanitize

Likely sanitize candidates:

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
- selected `docs/progress/*`

### Exclude

Strong exclude candidates:

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
- `.pytest_cache/`
- local generated artifacts
- `.DS_Store`

### Rehome privately

Keep only in the private origin:

- detailed internal progress logs
- private repo maps
- local machine context
- rollback/restore notes tied to private backups
- private research notes
- local operator habits and temporary work artifacts

## Maintainer Visibility

The public repository should keep visible maintainer attribution.

Required visibility:

- maintainer name in README
- LinkedIn reference in README
- maintainer identity in monitor where already shown

## Release Positioning

The first public release should be positioned as:

- experimental
- agent-first
- local-first
- serious and already useful
- still evolving

Recommended language:

> Agent Memory is an experimental, local-first memory and context engine for
> coding agents. It is already usable, but its public interface, documentation,
> and integration ergonomics are still evolving.

## Work Packages

## Wave 1 - Public Inventory And Boundaries

### W1.1 Path inventory

Create a complete path-by-path decision inventory in the copied public working
tree:

- keep
- sanitize
- exclude
- private-only

Acceptance:

- every top-level path has an explicit disposition
- no ambiguous runtime/private directories remain in scope

### W1.2 Runtime/source boundary definition

Formalize which content is:

- versioned source
- generated artifact
- runtime-local state
- private-only operator context

Acceptance:

- public docs and `.gitignore` strategy align
- `docs/knowledge` is formally deprecated as runtime storage

## Wave 2 - Structural Cleanup Of The Public Working Tree

### W2.1 Remove excluded material

Remove from the copied public working tree:

- runtime folders
- backup folders
- local IDE and hook artifacts
- test harnesses with local paths or transcript-like fixtures

Acceptance:

- no known private/runtime-only directories remain
- copied tree is materially smaller and public-safe

### W2.2 Runtime knowledge migration

Switch runtime repo knowledge from `docs/knowledge/` to `memory/knowledge/`.

Acceptance:

- installer, docs, and runtime references no longer present
  `docs/knowledge` as the public runtime contract

## Wave 3 - Activation Model Rewrite

### W3.1 Explicit activation model docs

Author clear public docs for:

- project-root mode
- central-installation mode
- wrapper mode

Acceptance:

- a user can determine when Agent Memory is active without reading runbooks
- wrapper-required vs wrapper-optional is explicit per client

### W3.2 Client activation matrix

Add a client-by-client activation matrix covering:

- startup mode
- root behavior
- wrapper behavior
- project activation behavior
- monitor/dream/query-expansion implications

Acceptance:

- all supported clients are covered
- Codex and Claude root behavior is clearly documented

## Wave 4 - README And Core Public Docs Rewrite

### W4.1 README rewrite

Rewrite the root README as a first-class public product README.

Acceptance:

- external user can understand the project, activation model, and quickstart
  from the README alone

### W4.2 Core architecture and setup docs

Rewrite or reorganize:

- architecture
- setup
- operator/control
- storage
- safety

Acceptance:

- the public docs tree is coherent and English-first
- agent navigation through docs is materially simpler

## Wave 5 - Public-Safe Design Context Carry-Over

### W5.1 Condense selected progress docs

Translate and condense selected progress/epic material into public-safe docs.

Acceptance:

- useful design and evolution context is preserved
- raw internal progress noise is not exposed

### W5.2 Origin note

Add a public-safe origin explanation to README and `docs/project-origin.md`.

Acceptance:

- the public repository transparently explains its private origin
- no private references leak through the explanation

## Wave 6 - Final Public Readiness Pass

### W6.1 Documentation consistency pass

Check all retained docs for:

- English-first language
- no private paths
- no stale `docs/knowledge` contract
- no misleading wrapper guidance

### W6.2 Product clarity pass

Verify that the public repository clearly communicates:

- what the system is
- when it is active
- where data goes
- how it is controlled
- how it is inspected
- how safety works

Acceptance:

- the copied public working tree is ready for later `git init`

## Acceptance Checklist

- [ ] public tree exists separately from private origin
- [ ] no `.git` carried over from private origin
- [ ] no private runtime data tracked in the public tree
- [ ] `docs/knowledge` removed from the public runtime contract
- [ ] `memory/knowledge` documented as local runtime knowledge location
- [ ] activation model rewritten and explicit
- [ ] root mode and wrapper mode documented as equal valid paths
- [ ] Codex and Claude root behavior clearly explained
- [ ] all supported clients documented
- [ ] README rewritten to public OSS quality
- [ ] public docs English-first
- [ ] German still supported in product/runtime where applicable
- [ ] maintainer name and LinkedIn still visible
- [ ] public origin note added
- [ ] selected design/epic history carried over only in condensed public-safe form
- [ ] copied public tree ready for later `git init`

## Execution Order

1. inventory and path classification
2. remove excluded material
3. migrate runtime knowledge contract
4. rewrite activation model
5. rewrite README and core docs
6. condense selected design/progress context
7. final public-readiness pass
8. only later: initialize public Git history

## Agent Execution Contract

This epic is intended to be executable largely by an agent.

The agent should be able to:

- curate the copied public working tree
- restructure docs
- rewrite English-first product documentation
- migrate runtime knowledge paths
- simplify the activation model
- preserve major product capabilities and explain them clearly

The agent must still defer to the user for:

- final naming
- final release positioning wording if disputed
- security-sensitive publication decisions
- final Git initialization and publication
