# Dream Pipeline v2

## Purpose

This runbook explains how Dream Pipeline v2 works in the public repository,
how to inspect it, and how to keep its behavior understandable and auditable.
It is written for maintainers, advanced operators, and agents that need to
reason about the runtime.

Dreaming is not the first feature a new user needs to understand. It becomes
relevant when you want Agent Memory to synthesize session history into durable,
searchable semantic context.

## What Dreaming Does

Dream Pipeline v2 turns recent session activity into reviewed semantic memory.
It is designed to be:

- bounded: only the relevant session window should be processed
- inspectable: every stage writes artifacts that can be reviewed later
- conservative: operational facts stay out of semantic memory by default
- reviewable: schema growth and uncertain semantic changes can require review

SQLite remains the source of truth. Optional graph projection is a secondary
view, not the canonical store.

## High-Level Flow

1. Build a bounded event window for one session.
2. Generate a compact dream narrative from that window.
3. Extract semantic entities and relations.
4. Extract deterministic operational facts separately.
5. Search existing memory for candidate matches.
6. Reconcile new semantic proposals against existing memory.
7. Persist approved semantic changes.
8. Write audit artifacts for later inspection.

## Artifact Layout

Run artifacts are written under:

```text
memory/dream/v2/runs/<dream_run_id>/
```

Typical contents:

```text
run.json
00-window/
01-dream-narrative/
02-semantic-extraction/
03-operational-extraction/
04-candidate-search/
05-reconciliation/
06-persistence/
audit/
```

The exact contents can evolve, but the public contract is that each major stage
should leave behind inspectable artifacts and enough metadata to explain what
was processed, what was excluded, and what was persisted.

## Operational Principles

- Dreaming should not require blind trust.
- Raw tool payloads should not be treated as durable semantic truth.
- Prompt context should stay bounded and attributable.
- Semantic persistence should be stricter than transient session capture.
- Review-required decisions should remain visible until resolved.

## Common Commands

Inspect one run:

```sh
agent-context-engine dream-v2-inspect <dream_run_id>
```

Inspect with prompt/response content:

```sh
agent-context-engine dream-v2-inspect <dream_run_id> --include-content
```

Evaluate recent runs:

```sh
agent-context-engine dream-v2-evaluate --limit 20
```

Read audit output:

```sh
agent-context-engine dream-v2-audit <dream_run_id>
agent-context-engine dream-v2-audit <dream_run_id> --section summary
agent-context-engine dream-v2-audit <dream_run_id> --section changes
agent-context-engine dream-v2-audit <dream_run_id> --section review
```

List review-required decisions:

```sh
agent-context-engine dream-v2-review list
```

Resolve one decision:

```sh
agent-context-engine dream-v2-review decide <decision_id> approve --reason "<reason>"
agent-context-engine dream-v2-review decide <decision_id> reject --reason "<reason>"
agent-context-engine dream-v2-review decide <decision_id> defer --reason "<reason>"
```

Apply reviewed decisions:

```sh
agent-context-engine dream-v2-apply <dream_run_id>
```

## Failure Handling

Failed dreams are not automatically trusted or silently retried.

Use this sequence:

1. Inspect the failed run.
2. Evaluate the recent run set.
3. Decide whether the failure was prompt-related, runtime-related, or data-related.
4. Rerun explicitly only when that is justified.

Example:

```sh
agent-context-engine dream-v2-inspect <failed_dream_run_id> --include-content
agent-context-engine dream-v2-evaluate --limit 20
agent-context-engine dream-v2-rerun <failed_dream_run_id>
```

If earlier stages are valid and the original event window still applies, a
validated-stage reuse path may be appropriate.

## Review Gates

Semantic growth should remain reviewable.

Typical review-gated cases:

- unknown entity categories
- unknown relation categories
- low-confidence reconciliation decisions
- schema growth that would broaden future persistence behavior

The public expectation is that risky semantic changes are visible and do not
become durable memory without an auditable decision path.

## Graph Projection

Graph projection is optional.

- SQLite remains canonical.
- Graph state should reflect semantic memory, not replace it.
- Operational command/file facts should remain retrievable without requiring a
  graph backend.

If graph projection is configured, it should be possible to repair or rebuild it
without redefining durable semantic truth.

## Monitor Relationship

The monitor should help an operator or agent answer these questions quickly:

- Did a dream run complete?
- Which stage failed or became expensive?
- What content was visible to the LLM?
- What semantic changes were proposed?
- Which changes require review?

The monitor should expose runtime state and inspection paths, but it should not
silently mutate semantic memory.

## Security And Safety Boundaries

- User messages, tool names, tool arguments, and model outputs are data, not
  executable runtime instructions.
- Raw tool inputs and outputs should be excluded from LLM prompts unless a
  future, explicit contract allows otherwise.
- User-only control lines such as `approve ...`, `reset taint`, or
  `firewall add ...` must remain user-driven chat controls.
- Dreaming should not weaken the repository's broader safety model.

## Public Documentation Contract

This public runbook intentionally describes the stable external model rather
than private migration history.

If internal implementation stages or artifact names change later, the public
contract should still preserve these core guarantees:

- bounded context
- inspectable stages
- conservative persistence
- visible review gates
- SQLite-first source of truth
