# Monitor Operator Workflows

## Purpose

This runbook explains how an operator should read and use the monitor when
working with runtime state, firewall state, approvals, overrides, and storage
health.

It focuses on operational interpretation and decision-making, not on internal
implementation details.

## Related Surfaces

The monitor should expose clear control-oriented surfaces for:

- overview
- approvals
- overrides
- firewall state
- storage and runtime health
- diagnostics

UI labels can differ by language. The public contract is about the workflow,
not one hard-coded locale.

## Operator Principles

1. Use the monitor to understand state before changing it.
2. Prefer the narrowest intervention that solves the current problem.
3. Treat overrides as temporary exceptions, not as a normal way to work.
4. Keep approvals, exceptions, and state changes auditable.
5. Do not use the monitor as a shortcut around user-only safety controls.

## Reading Order

When opening the control area, read it in this order:

1. overall health and runtime summary
2. pending approvals
3. active overrides
4. firewall state and quick actions
5. storage and runtime warnings
6. detailed rules, suggestions, and diagnostics

This keeps the operator focused on the current problem before moving into
background detail.

## Workflow A: Quick Health Check

Use this when you want to answer:

- is the system currently usable?
- is work blocked by the firewall?
- are approvals waiting?
- are there storage or runtime warning signs?

Suggested sequence:

1. Open the overview.
2. Check whether urgent control attention is required.
3. Open the control area.
4. Read the firewall header for enabled state, override count, and approval
   count.
5. Read the storage/runtime summary for warnings and footprint indicators.
6. Open diagnostics only if the earlier surfaces do not explain the issue.

Expected result:

- you can quickly decide whether the current issue is mainly policy-related,
  exception-related, infrastructure-related, or not an active control problem

## Workflow B: Pending Approvals

Use this when the system indicates approval-bearing risk events.

Read:

- affected tool or source
- approval state
- session or scope context
- timestamp
- recorded reason or preview

Interpretation:

- a pending approval is a decision request, not automatically a system failure
- the relevant scope may be local even when the symptom feels global

Operator action model:

1. Identify the affected session or work scope.
2. Confirm whether the approval request is expected.
3. Inspect related risk detail when the reason is unclear.
4. Follow the appropriate explicit approval path when policy requires it.

Do not assume that every pending approval should be solved through a broad
exception.

## Workflow C: Active Overrides

Use this when work is currently possible only because of temporary exceptions,
or when you suspect stale allowances.

Read per override:

- scope
- reason
- expiration
- identifier

Interpret scope conservatively:

- `session`: best default when only one active thread needs relief
- `project`: useful when repeated work inside one project needs the same
  temporary exception
- `workdir`: useful when the exception is tied to one local folder
- `agent`: narrow runner-specific exception
- `global`: widest and highest-risk exception surface

Operator action model:

1. Ask whether the override is still needed.
2. Prefer the narrowest scope that fits the actual work.
3. Revoke stale overrides promptly.
4. Replace broad overrides with narrower ones when possible.

Healthy pattern:

- few active overrides
- clear reasons
- short lifetimes
- narrow scope

Concerning pattern:

- many concurrent overrides
- vague reasons
- repeated extension without root-cause follow-up
- broad exceptions solving narrow problems

## Workflow D: Creating An Override

Use this only when normal operation is blocked and a temporary exception is
operationally justified.

Recommended sequence:

1. Choose the narrowest scope possible.
2. Write a reason that explains the operational need, not only the symptom.
3. Keep the duration short.
4. Bind the override to session, project, or workdir when the issue is local.

Good reasons:

- "Temporary session exception while investigating a false positive"
- "Allow local workdir operation during migration audit"

Weak reasons:

- "needed"
- "temporary"
- "does not work"

After creation:

1. Re-check the active override list.
2. Confirm the scope and expiration.
3. Return to the blocked workflow and verify that only the intended work is now
   possible.

## Workflow E: Revoking An Override

Use this when a temporary exception is no longer needed or was created too
broadly.

Operator action model:

1. Verify the target override by reason and scope.
2. Revoke it.
3. Re-check the active override list.
4. If work breaks again, determine whether the override was still needed or the
   underlying issue was never resolved.

## Workflow F: Firewall State And Quick Actions

Use this when the system appears globally blocked or overly permissive.

Interpretation:

- quick actions are coarse operational levers
- they are useful for short-lived operating state changes
- they are not a permanent replacement for policy

Recommended pattern:

1. Use quick actions when the overall operating state is the problem.
2. Use scoped overrides when only a local exception is needed.
3. Review rules and suggestions later if the same issue repeats.

## Workflow G: Rules And Suggestions

Use this when the same approvals, blocks, or exceptions keep recurring.

Interpretation:

- fixed rules form the durable policy base
- dynamic rules reflect time- or context-sensitive behavior
- suggestions are potential improvements, not active truth on their own

Operator action model:

1. Confirm the current symptom through approvals or overrides first.
2. Inspect rules or suggestions to determine whether the issue is structural.
3. Use this section to inform later policy work, not as the first everyday
   operating surface.

## Workflow H: Storage And Runtime

Use this when you need to understand local memory footprint, runtime paths,
database state, or graph presence.

Read in order:

1. warnings
2. footprint indicators
3. project root and memory directory
4. database files and table counts
5. important paths
6. graph projection status
7. cleanup hints

Typical questions this surface should answer:

- where is the runtime writing?
- is SQLite present and growing?
- do expected memory categories exist?
- is graph projection configured and populated?
- are there cleanup tasks worth scheduling outside the monitor?

## Workflow I: Diagnostics

Use diagnostics only after the primary control surfaces.

Use it for:

- runtime confirmation
- configuration clues
- checking whether a problem is infrastructural rather than policy-related

Do not make it the first stop for everyday approval or override questions.

## Escalation Boundaries

Use the monitor for:

- understanding state
- finding the affected session, dream, or control context
- creating or revoking auditable temporary overrides where supported
- reading rules, suggestions, warnings, and diagnostics

Do not use the monitor alone for:

- bypassing user-only approval controls
- making permanent policy changes without the correct backend or agent path
- destructive cleanup without an explicit audited contract

## Healthy End State

The operator should be able to answer these questions quickly:

- What is blocked right now?
- Is the problem approval-related or infrastructure-related?
- Is there an active exception, and is it still justified?
- Which session or scope is affected?
- Is storage and runtime behavior plausible?

If the monitor cannot answer those questions within a short scan, the next
iteration should improve the product rather than rely on operator memory.
