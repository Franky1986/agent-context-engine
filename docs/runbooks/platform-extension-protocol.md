# Platform Extension Protocol

Status: active contributor protocol
Related epic: `docs/epics/platform-capability-agent-flow-refactor-plan.md`

## Purpose

Define the required artifacts, fields, tests, and support-level rules for
adding or changing platform support in Agent Context Engine.

This protocol exists so future platform work stays explicit, conservative, and
auditable. New platform code must extend the capability model and adapters
without accidentally claiming runtime support that has not been earned.

## Applies To

Use this protocol when a change introduces or modifies behavior for:

- `linux`
- `wsl`
- `windows`
- `posix_generic`
- any future platform family beyond the active macOS path

## Core Rules

1. New platforms start as `scaffolded` unless there is real runtime evidence.
2. Support claims above `scaffolded` require matching `evidence` metadata.
3. Platform identity alone must not enable destructive runtime mutation.
4. Diagnostics must state unsupported, degraded, scaffolded, or supported
   states explicitly.
5. Hook, wrapper, scheduler, publication, quoting, and permission behavior must
   flow through the existing ports and runtime-selection boundary.

## Required Artifacts

Every new platform contribution must include, at minimum, the relevant updates
below.

### 1. Platform profile and capability matrix

Required area:

- `backend/src/agent_context_engine/application/platform/profile.py`

Required work:

- add or update the `PlatformFamily` entry if needed
- define the platform profile support level and evidence level
- define the capability statuses for:
  - scheduler backend
  - global command publication
  - wrapper rendering
  - hook adapter runtime
  - agent guidance rendering
  - shell rendering family
  - browser file open
  - process launch behavior
  - workspace binding behavior
  - executable permission strategy
  - symlink shim strategy
  - path quoting strategy

### 2. Runtime selection wiring

Required areas, as applicable:

- `backend/src/agent_context_engine/application/platform/runtime_selection.py`
- `backend/src/agent_context_engine/application/platform/runtime_summary.py`

Required work:

- select the platform-specific adapters through the runtime-selection boundary
- surface the selected adapters in runtime summaries and diagnostics

### 3. Adapter implementation or scaffold

Required areas depend on the capability being changed:

- scheduler installers
- command publishers
- hook adapter renderers
- wrapper renderers
- process launch adapters
- workspace binding adapters
- executable permission adapters
- path quoting adapters
- system-open adapters

Required work:

- add a real adapter or an explicit scaffolded adapter
- expose `adapter_name`, `support_level`, and `evidence`
- ensure scaffolded adapters do not perform unsafe runtime mutation

### 4. Declarative render specs

Required area:

- `backend/src/agent_context_engine/application/hook_rendering/specs.py`

Required work:

- add or update hook/wrapper spec builders when a new render family or wrapper
  shape is introduced
- keep renderer inputs declarative instead of passing ad hoc argument bundles

### 5. Diagnostics and operator visibility

Required areas:

- `backend/src/agent_context_engine/application/diagnostics.py`
- `backend/src/agent_context_engine/application/monitor.py`

Required work:

- show the platform profile and selected runtime adapters
- ensure scaffolded or unsupported platform states are visible to operators
- add explicit text for degraded or unsupported behavior where applicable

### 6. Documentation

Required areas, as applicable:

- nearest `*.spec.md` files for changed boundaries
- `docs/index.md`
- user-facing setup or runbook docs when behavior changes for operators

Required work:

- update the nearest specs in the same patch
- add the new document to `docs/index.md` when introducing a durable doc
- document public OS assumptions and any runtime caveats

## Required Metadata

Every new platform contribution must keep these metadata dimensions explicit:

- `support_level`
- `evidence`
- capability `status`
- adapter name
- render/spec version where a managed script or system artifact is generated

## Support-Level Rules

### `unsupported`

Use when:

- the platform is known not to work
- no safe scaffold is available

Requirements:

- diagnostics must say it is unsupported
- no runtime mutation path may activate by default

### `scaffolded`

Use when:

- structure exists for future work
- behavior is based on design knowledge or public docs only

Requirements:

- no destructive or privileged runtime mutation by default
- clear diagnostics text
- contract tests for the scaffolded adapter or selection path

### `experimental`

Use when:

- behavior can run intentionally
- maintainers accept that the path is not production-supported yet

Requirements:

- explicit runtime gate or opt-in
- smoke evidence or equivalent targeted runtime proof
- documented caveats

### `smoke_validated`

Use when:

- at least one real runtime pass exists on the target platform

Requirements:

- smoke-test evidence recorded
- diagnostics and operator docs updated

### `operator_validated`

Use when:

- repeated real workflow evidence exists

Requirements:

- operator-visible success path is documented
- degraded cases are documented

### `supported`

Use when:

- the platform is a maintained production path

Requirements:

- characterization or golden coverage for key outputs
- real runtime evidence
- operator docs and maintenance expectations are in place

## Required Test Coverage

Every platform contribution must add the relevant mix of:

- characterization tests for current behavior
- golden tests for generated instruction or script artifacts
- adapter contract tests
- runtime-selection summary tests
- diagnostics text tests

At minimum, new platform work must cover:

1. platform profile selection
2. runtime adapter selection
3. diagnostics visibility
4. generated hook or wrapper artifacts if rendering changes
5. scheduler behavior gating if scheduler capability changes

## Promotion Checklist

Use this checklist when raising a platform from `scaffolded` to
`experimental`, or higher.

- real target platform available
- runtime mutation path exercised on the target platform
- failure behavior inspected
- diagnostics text confirmed
- hook/wrapper outputs confirmed
- scheduler behavior confirmed if applicable
- support level and evidence level updated together
- relevant docs and specs updated together

## Contributor Checklist Template

Copy this checklist into the change note or PR description for any new platform
contribution.

- [ ] platform profile added or updated
- [ ] capability matrix updated
- [ ] runtime-selection wiring updated
- [ ] runtime summary/diagnostics updated
- [ ] adapters added or scaffolded behind existing ports
- [ ] declarative hook/wrapper specs updated if rendering changed
- [ ] support level and evidence level set explicitly
- [ ] scaffolded paths remain disabled or non-destructive by default
- [ ] tests added for profile, selection, diagnostics, and generated outputs
- [ ] nearest specs updated
- [ ] docs/index updated if a durable doc was added
- [ ] public OS assumptions documented
- [ ] promotion checklist considered if support level moved above `scaffolded`

## Current Policy Note

As of this protocol:

- macOS is the only active supported runtime path
- native Windows is a real target platform, but not yet runtime-enabled here
- Linux, WSL, and generic POSIX remain scaffolded until real evidence exists
