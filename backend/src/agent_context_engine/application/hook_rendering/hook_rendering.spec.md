# Spec: Hook And Wrapper Rendering Application Boundary

## Purpose

Represent shell hook adapter and wrapper rendering as a centralized application
boundary so platform- and shell-sensitive script generation is no longer spread
across installation and integration-management code paths.

## Scope

- Rendering managed shell hook adapter scripts from maintained templates.
- Rendering the managed Cursor project hook wrapper.
- Defining declarative hook and wrapper render specs before shell-specific
  rendering.
- Keeping current Bash/macOS-visible output stable while renderers are
  extracted.

## Non-Scope

- Hook config JSON merge logic.
- Global command publication and symlink strategy.
- Platform-specific scheduler installation behavior.
- Future PowerShell, cmd, or Windows-native renderers.

## Responsibilities

- Keep hook/wrapper script rendering deterministic.
- Use one application boundary for template-based shell hook generation.
- Keep render inputs explicit as stable spec objects instead of loose argument
  bundles.
- Make injected root/script paths explicit inputs.
- Preserve the current active Bash renderer contract until another renderer is
  introduced intentionally.
- Scaffolded renderers must surface support/evidence metadata explicitly instead
  of pretending to be runtime-ready scripts.

## Inputs / Outputs

- Inputs: target client, installation root, script path, template selection.
- Outputs: rendered shell script text for hook adapters and managed wrappers.

## Dependencies / Ports

- May depend on repository-managed script templates.
- Must not decide support level or platform policy by itself.

## Failure Modes

- Unsupported clients fail explicitly.
- Missing templates fail explicitly.
- Renderers must not silently emit partially substituted placeholder output.

## Acceptance Criteria

- Installation flow and integration-management flow share the same shell hook
  adapter renderer.
- Cursor managed project hook wrapper is rendered from one application entry.
- Managed hook/wrapper render inputs can be represented as declarative specs
  before renderer selection.
- Existing Bash/macOS behavior remains the active rendered path.
- Scaffolded non-Bash renderers expose deterministic metadata-only output with
  explicit support/evidence lines.

## Tests / Checks

- `python3 tests/test_agent_context_engine.py`

## Agent Guardrails

- Do not duplicate shell script render logic in multiple modules when the
  centralized renderer can be used instead.
- Do not introduce scaffolded platform renderers as active runtime defaults.
