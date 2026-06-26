# Spec: Hook Interface Boundary

## Purpose
Receive agent hook and plugin-bridge events, normalize payloads, apply
pre-action safety checks, and enqueue or persist events for later processing.

## Scope
- Codex, Claude, Cursor, Antigravity, Gemini, and Opencode ingress.
- Payload normalization, queue fallback, risk gate invocation, and session
  context handling.

## Non-Scope
- Dream/graph execution.
- Long-running scheduler work.
- UI presentation.

## Responsibilities
- Keep hook handling fast and robust under concurrent agent activity.
- Fail closed for risky pre-action checks when required.
- Preserve queued payloads when SQLite is temporarily unavailable.
- Keep asynchronous queue scheduling observable so operators can see whether a
  worker is running, stale, or replaying queued events.
- Distinguish local read-only file/context access from network reads so tainted
  local inspection can warn while remote fetches still block.
- Return concrete user guidance for taint-driven blocks, including the
  triggering risk ids and valid direct-chat control lines.
- Prefer the public `agent-context-engine` command in generated session-start
  and hook guidance when the active installation owns that global link.

## Inputs / Outputs
- Inputs: hook JSON payloads, environment metadata, transcript/session hints.
- Outputs: persisted event rows, queue files, allow/block hook responses.
  Block responses must explain whether the attempted action was read/write/
  network-like, cite active taint source ids when present, and surface valid
  user-only follow-ups (`approve ...`, `reset taint`, session firewall
  controls, hook control-plane commands) without requiring a second
  clarification turn.

## Dependencies / Ports
- Application hook effects and risk/firewall services.
- SQLite/event persistence.
- Lock and queue support.

## Failure Modes
- Malformed payloads are rejected or quarantined with traceable metadata.
- Busy database writes use queue fallback where safe.
- PreToolUse risk blocks return a clear blocked response.

## Observability / Audit
- Risk decisions and queued fallback events must be inspectable later.
- Session correlation should preserve launch and working directory context.
- Queue health, bridge error logs, and worker status must be externally
  inspectable through diagnostics and monitor status payloads.

## Acceptance Criteria
- Existing Codex/Claude/Cursor/Antigravity/Gemini/Opencode integrations continue to work.
- Hook paths do not run dream/graph work inline.
- Queue replay can recover accepted events.
- `beforeReadFile` and equivalent local file/context reads after taint are
  warned and audited, not blocked.
- Remote/network reads remain risk-gated even when the upstream tool frames
  them as read-like operations.
- Cursor classifier runner auth failures fall back to deterministic policy and
  operator guidance instead of creating tainting `classifier_invalid_output`
  cascades.
- Windows hook adapters must give user-scoped command shims such as
  `%APPDATA%\npm` and `%USERPROFILE%\.local\bin` precedence for internal
  runner subprocesses, and classifier runner launch failures must fall back to
  deterministic policy instead of creating tainting `classifier_invalid_output`
  cascades.
- Cursor auth readiness checks must treat textual unauthenticated states such
  as `Not logged in` as not-ready even when `cursor-agent status` exits `0`.
- Cursor queue reservation and later replay must preserve the resolved
  headless background runner (`codex` or `claude`) instead of falling back to
  `cursor` during the provisional session-row write.
- When a queued hook reserves a new event for an already summarized or dreamed
  session, the session row must revert to `summary_pending` / `dream_pending`
  immediately so install-wide diagnostics do not keep stale fully-covered
  states while uncovered work is waiting in the queue.
- Cursor startup guidance and early prompt blocking must validate the delegated
  background runner's real auth-readiness, not just whether a `codex` or
  `claude` binary exists in `PATH`.
- Hook/session command rendering should point at the active installation's
  public CLI when available, not stale repo-local shortcuts from a superseded
  installation.
- Internal Agent Context Engine subprocesses such as auth/readiness probes,
  classifier runs, dreaming, query expansion, monitor asks, and graph LLM
  passes must bypass hook capture so they do not create fake user-visible
  sessions.

## Tests / Checks
- `python3 tests/test_agent_context_engine.py`
- `agent-context-engine doctor`

## Agent Guardrails
- Do not persist raw tool output bodies.
- Do not add slow runner calls to hook request handling.
- Do not weaken hook or firewall protections through alternate control paths.
- Direct user chat control lines for session firewall changes are allowed;
  direct user chat control lines for `hooks-disable`, `hooks-enable`, and
  `hooks-status` are also allowed; normal agentic hook-disable attempts are
  not.
