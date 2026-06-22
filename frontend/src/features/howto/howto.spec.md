# Spec: Monitor Howto Feature

## Purpose

Explain what Agent Context Engine is, how hooks/runners/firewall/monitor fit
 together, and where users should go next after installation.

## Scope

- static monitor howto content
- visual relationship overview between user, runner, hooks, memory, dreams, and monitor
- internal jump actions to existing monitor sections
- install-driven deep-link entry via `#howto`

## Non-Scope

- direct monitor-side mutation of protected control-plane actions
- backend API orchestration
- replacing operational monitor tabs with marketing content

## Responsibilities

- provide the first-use orientation screen for a fresh install
- explain why some actions stay on the explicit user chat path
- distinguish project-based GUI runners from global-only wrappers
- route all copy through frontend i18n

## Acceptance Criteria

- the app shell exposes `Howto` as the rightmost top-level tab
- `#howto` opens the howto section directly
- action buttons only jump to existing monitor sections
- the howto includes a visual flow explanation and links to integrations/control/sessions/knowledge/personal/overview

## Tests / Checks

- `npm --prefix frontend run build`
- app-shell routing keeps `#howto` stable
