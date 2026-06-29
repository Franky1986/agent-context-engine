# Spec: Agent Flow Application Boundary

## Purpose

Represent agent-facing startup instructions and retrieval workflow guidance as a
structured application contract so all rendered instruction targets stay aligned
across installation, hook startup, and harness entrypoints.

## Scope

- Canonical agent-flow contract fields.
- Rendering of agent-facing instruction artifacts.
- Stable wording for retrieval, handover, repo-context, monitor, and
  user-control guidance, including the canonical runtime repo-index location.

## Non-Scope

- Concrete hook adapter shell behavior.
- Concrete wrapper/symlink rendering.
- Concrete scheduler or platform adapter implementation.
- Personal-context loading logic itself.

## Responsibilities

- Keep generated startup/instruction artifacts consistent.
- Remove drift between installation-time and runtime startup guidance.
- Make command prefix, repo-context path, public-CLI repair stance, and monitor
  startup defaults explicit inputs.
- Preserve current macOS-visible instruction behavior while boundaries are
  extracted.

## Inputs / Outputs

- Inputs: command prefix, preferred language, canonical repo-index location
  within the active memory root,
  monitor runner, monitor host/port defaults, and public-CLI expectations.
- Outputs: rendered markdown/text artifacts for agent-facing startup surfaces.

## Dependencies / Ports

- May depend on installation profile read models for selected runner defaults.
- Must not depend on concrete shell hook adapters or LaunchAgent behavior.

## Failure Modes

- Unknown languages fall back to English labels.
- Missing monitor runner falls back to the documented default.
- Renderers must stay deterministic for the same contract input.

## Acceptance Criteria

- `AGENTS.md` quick-path block is rendered from the shared contract.
- `session-start-hook-entry.md` is rendered from the shared contract.
- `CLAUDE.md` and Cursor every-chat entrypoint text come from the same boundary.
- Installation and hook-session startup no longer maintain separate default
  wording for the same retrieval workflow.
- Repo/project routing guidance must prefer `repo-context` commands and treat
  `memory/knowledge/repos.md` as the canonical runtime repo index.
- Public-CLI/PATH repair guidance and monitor startup defaults stay aligned
  between the shared contract and the checked-in startup docs.
- Session start guidance uses a one-time CLI prefix declaration followed by
  prefix-less subcommands for startup command families.
- User-only `approve`/`firewall`/`workdir` controls are rendered conditionally
  based on active block/taint/firewall context and not included as permanent
  startup noise.
- Session start context supports staged injection: compact default + trigger-based
  enrichment on demand.

## Tests / Checks

- `python3 tests/test_agent_context_engine.py`
- `python3 scripts/update_docs_index.py --check`

## Agent Guardrails

- Do not duplicate agent-flow wording in separate render paths when the shared
  contract can express it.
- Do not claim unsupported platform/runtime behavior through rendered guidance.
- Do not keep permanent `User-only controls` in startup contexts that are not
  actually actionable for that session state.
