# Epic / UX Plan: Guided Installation and Language-Aware Onboarding

> Status 2026-06-22: **implemented in the current production slice**.
> `install-discovery` is read-only, detects checkout root and checkout role,
> finds plausible existing `memory_root` candidates, reports wrapper conflicts
> and LaunchAgent identity, returns a structured recommended install plan, and
> suggests safe defaults for `agent-context-engine` such as isolated monitor
> ports, a `-ace` wrapper suffix, and delayed LaunchAgent activation.
> `install` without `--target` now uses that discovery context for a guided
> entry flow, keeps prompts and summaries in the chosen language, blocks
> accidental public-to-source mutations, can adopt an existing `memory_root`
> after confirmation, and automatically runs `doctor` and
> `check-installation` afterward.

> Product rule: suggested defaults are not silent mutations. The user must
> explicitly approve the target root, memory root, monitor port, wrapper
> naming, and any in-place refresh before files are written.

## Problem

The installation surface became functionally strong, but the onboarding path
was still too technical. A fresh public checkout should not require the user to
understand CLI flags, internal repository layouts, or old runtime-storage
paths before the first successful install.

## Target Behavior

From a short prompt such as `install this`, the agent should:

1. detect the checkout and role,
2. discover plausible runtime-storage candidates,
3. suggest safe defaults,
4. summarize those defaults in the user's language,
5. wait for explicit approval,
6. execute the correct install or refresh path,
7. verify with `doctor` and `check-installation`,
8. summarize the resulting setup in plain language.

## Current Public Defaults

For a fresh `agent-context-engine` checkout, discovery may suggest:

- the current checkout as the install target,
- an existing `memory_root` when one is confidently detected,
- an isolated monitor port when `8787` is already occupied,
- the wrapper suffix `-ace` for multi-install safety,
- deferred LaunchAgent installation until the user wants the background worker.

Those values are proposals, not implicit consent.

## Guardrails

- A public checkout must not silently mutate a separate source checkout.
- A detected existing installation must not be refreshed in place without an
  explicit user confirmation.
- Suggested wrapper names must not be shown as available global commands unless
  matching links were actually created.
- Suggested defaults must be visible in discovery output before any mutation.

## Acceptance Criteria

This epic is materially complete when:

1. `install-discovery` is read-only.
2. Checkout-role detection distinguishes public, source, and existing-install
   cases.
3. Discovery output includes target, memory root, monitor port, wrapper
   naming, LaunchAgent recommendation, and a clear user-confirmation warning.
4. Interactive install shows a final install-plan confirmation before writing.
5. Successful installs always run `doctor` and `check-installation`.
6. Public-checkout installs cannot silently mutate a different checkout.
