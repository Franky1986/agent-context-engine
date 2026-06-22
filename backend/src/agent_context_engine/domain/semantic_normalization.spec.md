# Spec: Semantic Normalization Domain

## Purpose
Define deterministic semantic normalization rules and value objects for
canonical entity and relation naming before semantic candidate search and
persistence.

## Scope
- Canonical name selection.
- Key derivation.
- Alias consolidation.
- Lightweight language detection.
- Relation summary/key normalization.

## Non-Scope
- SQLite persistence.
- Dream orchestration.
- LLM review of learned normalization rules.
- Retrieval ranking and monitor formatting.

## Responsibilities
- Produce stable, testable normalization outputs from primitive proposal data.
- Stay deterministic and free of infrastructure or adapter imports.
- Preserve enough trace metadata to explain normalization decisions.

## Inputs / Outputs
- Inputs: raw entity/relation proposal fields and aliases.
- Outputs: normalized value objects with canonical names, keys, aliases, and
  traces.

## Dependencies / Ports
- Standard library only.

## Failure Modes
- Empty or weak input remains representable through fallback canonicalization.
- Unknown languages fall back to conservative heuristics instead of throwing.

## Acceptance Criteria
- Domain normalization can be unit tested without SQLite or runners.
- The same input yields the same canonical name/key every time.
- Normalization trace explains meaningful transformations.

## Tests / Checks
- `python3 tests/test_agent_context_engine.py`
- `./scripts/check --skip-runtime-db`
