# Spec: Dream Semantic Normalization

## Purpose
Normalize semantic proposals after semantic extraction and before candidate
search, reconciliation, and persistence in Dream v2.

## Scope
- Application orchestration over normalized entity/relation proposals.
- Attaching normalization metadata to proposal payloads.
- Producing inspectable normalization-stage artifacts.

## Non-Scope
- Raw LLM semantic extraction.
- Learned-rule rollout.
- Monitor UI rendering.

## Responsibilities
- Convert raw semantic payloads into canonicalized proposals.
- Preserve original labels alongside canonicalized names.
- Ensure downstream stages receive normalized inputs.
- Prefer prompt-driven semantic canonicalization for stable cross-language
  entity names instead of hardcoded deterministic translation tables.

## Inputs / Outputs
- Inputs: validated semantic payload from semantic extraction.
- Outputs: normalized semantic payload with per-proposal normalization metadata.

## Dependencies / Ports
- Semantic normalization domain rules.
- Dream stage/artifact persistence from the dreaming application boundary.

## Failure Modes
- Malformed proposal shapes should remain validation failures upstream.
- Missing aliases should not block deterministic normalization.
- Language-specific source content should not force unsafe or overconfident
  deterministic translations of proper nouns, product names, repo names, or
  commands.

## Acceptance Criteria
- Candidate search runs on normalized proposal names and aliases.
- Persisted proposal keys are derived from normalized canonical forms.
- Stage artifacts show original and normalized values for inspection.
- The semantic prompt explicitly instructs the model to prefer stable English
  canonical names when appropriate while preserving source-language aliases.

## Tests / Checks
- `python3 tests/test_agent_context_engine.py`
- `./scripts/check --skip-runtime-db`
