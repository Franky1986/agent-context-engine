# Dream Tokens Optimization TODO

## Goal
Reduce token consumption in Dream v2 runs while keeping semantic quality and reconciliation correctness.

## Scope
Targeted to Dream v2 stages and prompt payload construction:
- `backend/src/agent_context_engine/application/dreaming/v2_refactor/services/prompting.py`
- Stage entry points in `.../stages/{narrative.py,semantic.py,reconciliation.py}`
- Session context helpers in `backend/src/agent_context_engine/application/dreaming/v2.py`

---

## 1) Remove non-essential metadata from model prompts
- [ ] Remove `session_id` / `project_id` / `client_type` JSON blocks from prompt body where they are not directly required for inference.
- [ ] Keep identifiers for observability, but inject them after LLM output parsing in stage code.
- [ ] Add a minimal metadata block only when needed for rule disambiguation.

**Expected effect:** small single-digit to low-double-digit token reduction in all three stages.

---

## 2) Shorten schema contract examples
- [ ] Replace long `## JSON Schema Contract` examples with compact placeholder skeletons.
- [ ] Omit verbose prose around every field in prompt examples.
- [ ] Keep one canonical example per stage with required/optional fields only.

**Expected effect:** direct reduction of prompt tokens, especially for semantic and reconciliation.

---

## 3) Trim reused context passed into prompts
- [ ] Cap same-session semantic context and proposal payloads more aggressively.
- [ ] Ensure truncation happens before JSON stringification, not after, to avoid passing oversized JSON objects.
- [ ] Keep only fields used by model decisions.

**Expected effect:** prevents hidden growth in semantic/reconciliation prompts when context becomes noisy.

---

## 4) Reorder and compress narrative content
- [ ] In narrative prompt, move low-value sections after required constraints and reduce verbosity in static preamble.
- [ ] Use tighter wording for repeated instructions across stages.
- [ ] Consider deduplicating identical instruction chunks via shared minimal header.

**Expected effect:** lower prompt overhead and better budget headroom across long windows.

---

## 5) Improve reuse strategy for previous run data
- [ ] In narrative and semantic prompts, prefer deterministic summaries instead of full reused chunks when available.
- [ ] Use high-signal excerpt extraction for `dream_markdown`/handover history instead of fixed max-size slicing.

**Expected effect:** less waste from stale or low-signal historical content.

---

## 6) Validate and measure with hard budgets
- [ ] Add per-stage token-budget assertions for:
  - `dream_narrative`
  - `semantic_extraction`
  - `reconciliation`
- [ ] Track p95 token usage before/after each change and fail CI only on regression windows defined as large increases.

**Expected effect:** prevents accidental prompt bloat creep.

---

## 7) De-risk rollout
- [ ] Roll out in stages:
  - 1) schema contract compression
  - 2) metadata trimming
  - 3) context truncation tuning
- [ ] Keep a temporary feature flag for the new lean prompt path.
- [ ] Compare output parity on known scenarios.

---

## Quick acceptance criteria
- [ ] Median prompt token usage is reduced across all three stages.
- [ ] Existing semantic/reconciliation validator constraints still pass.
- [ ] No increase in low-confidence defers due to missing required metadata.
- [ ] No schema failures in dream pipeline due to contract simplification.
