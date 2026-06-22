# Spec: Normalization Learning

## Purpose
Define the future application boundary for autonomous normalization-rule
proposal, evaluation, LLM review, and rollout.

## Scope
- Rule proposal lifecycle.
- Evaluation and review orchestration.
- Rollout states for learned normalization rules.
- Multiple learned rule families such as alias families and title families.

## Non-Scope
- Deterministic first-pass normalization itself.
- UI workflows.
- Manual human review requirements.

## Responsibilities
- Keep learned-rule evolution auditable.
- Ensure rule proposals are evaluated before activation.
- Allow LLM-mediated review and staged rollout.

## Inputs / Outputs
- Inputs: observed normalization misses, merges, duplicates, and evaluation
  corpus results.
- Outputs: rule proposals, evaluation results, review outcomes, rollout states.

## Dependencies / Ports
- Rule repositories.
- Evaluation runner.
- LLM review port.
- Reviewer implementations must remain swappable so deterministic review can be
  replaced by a real LLM-backed adapter later.

## Failure Modes
- Weak proposals remain non-active.
- Harmful rules must be eligible for rollback.

## Acceptance Criteria
- Learned rules never skip evaluation and review.
- Rule rollout state is explicit and queryable.
- Existing deterministic rules remain usable without the learning loop.
- More than one learned rule family can be proposed and activated independently.

## Tests / Checks
- `python3 tests/test_agent_context_engine.py`
- `./scripts/check --skip-runtime-db`
