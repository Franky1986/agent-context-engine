# Spec: Dreaming Application Boundary

## Purpose
Run the active Dream v2 pipeline that condenses session windows into structured
memory artifacts and graph-ready proposals.

## Scope
- Dream candidate selection, prompt assembly, runner policy use, stage tracking,
  artifact validation, repair handoff, and persisted run status.
- v2 is the only active runtime path.

## Non-Scope
- Legacy v1 execution.
- Direct Neo4j adapter calls.
- Monitor UI rendering.

## Responsibilities
- Keep `dream_runs`, `dream_stage_runs`, and `dream_artifacts` lifecycle states
  coherent.
- Enforce token/input preflight limits before invoking a runner.
- Produce auditable failures such as invalid classifier or graph patch outputs.
- Keep semantic persistence conservative when evidence is weak, synthetic, or
  only inferred from a dream summary.
- Expose stage-level semantic signal classification and review/defer behavior
  as part of the audit trail.
- Keep runner-family-specific non-interactive command contracts current instead
  of silently depending on stale legacy CLI flags.

## Inputs / Outputs
- Inputs: session/window identifiers, runtime config, runner selection policy.
- Outputs: dream run records, stage records, artifacts, graph repair requests.

## Dependencies / Ports
- Runner resolution from `application/dream.py`.
- SQLite dream/run/artifact persistence.
- Graph application repair/sync ports.
- File rendering for review artifacts.

## Failure Modes
- Missing runner marks the run/pending state explicitly.
- Invalid model output is stored as an auditable invalid-output status.
- Oversized inputs are rejected before runner invocation.
- Low-signal windows must not silently create durable semantic entities whose
  required confidence or evidence contract is not met.
- Semantic evidence that cannot be grounded in the conversation window must not
  be treated as normal durable evidence.
- Stale runner CLI flags must fail as auditable runner errors rather than being
  silently retried through undocumented alternate modes.
- Structured JSON stages must not fail hard only because a runner returned
  blank, fenced, or mixed-text JSON output; the parse failure must stay
  auditable and fall back conservatively where the stage contract allows it.

## Observability / Audit
- Stage status must show what was planned, sent, generated, validated, and
  persisted.
- Human-readable audit artifacts must remain linked to the run.
- Semantic stages should make signal classification and review/defer posture
  inspectable through stored metadata and validation artifacts.

## Acceptance Criteria
- Dream v2 runs never silently fall back to v1.
- Failed stages are recoverable or explainable through stored artifacts.
- Graph patch repair can be retried without mutating historical run evidence.
- Cursor-backed dream runs should preserve truthful token accounting when the
  runner emits usage metadata.
- Semantic persistence must prefer grounded evidence from the actual
  conversation window over paraphrase from dream summaries.
- Antigravity-backed dream stages use the current non-interactive
  `agy --model "<model>" -p "<prompt>"` command contract.
- Semantic extraction and reconciliation use the same resilient JSON parsing
  contract across all supported runners and fall back deterministically when
  parsing fails.

## Tests / Checks
- `python3 tests/test_agent_context_engine.py`
- `agent-context-engine doctor`

## Agent Guardrails
- Do not reintroduce v1 runtime paths.
- Do not call runner adapters directly from interface code.
