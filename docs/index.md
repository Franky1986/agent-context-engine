# Documentation Index

This index is the first stop for architecture, operation, and spec-driven
development references in this repository.

## Active References

- [System Overview](architecture/SYSTEM_OVERVIEW.md)
- [Monitor Architecture](architecture/MONITOR_ARCHITECTURE.md)
- [Contracts](architecture/CONTRACTS.md)
- [Refactor Target Map](architecture/REFACTOR_TARGET_MAP.md)
- [Domain Model](architecture/DOMAIN_MODEL.md)
- [Current Status](progress/CURRENT_STATUS.md)
- [Next Steps](progress/NEXT_STEPS.md)
- [Structure Snapshot](progress/2026-06-03-structure-snapshot-validated.md)
- [Semantic Normalization Epic](progress/2026-06-03-semantic-normalization-epic.md)
- [Cross-Session Dream Evaluation](progress/2026-06-03-cross-session-dream-evaluation.md)
- [Monitor Inspect / UX Consolidation](progress/2026-06-03-monitor-inspect-ux-consolidation.md)
- [Monitor UX Analysis Report](progress/2026-06-03-monitor-ux-analysis-report.md)
- [Monitor UX / IA Epic](progress/2026-06-03-monitor-ux-epic.md)
- [Monitor UX Implementation Progress](progress/2026-06-04-monitor-ux-implementation-progress.md)
- [Hook Startup / Cursor Auth Hardening](progress/2026-06-04-hook-startup-and-cursor-auth-hardening.md)
- [Generic Client / Runner Integration Epic](progress/2026-06-04-client-runner-integration-epic.md)
- [Monitor Language Refactoring Epic](progress/2026-06-05-monitor-language-refactoring-epic.md)
- [Monitor I18n Centralization](progress/2026-06-05-monitor-i18n-centralization.md)
- [Control Plane Hardening](progress/2026-06-05-control-plane-hardening.md)
- [Agentic Retrieval Status Quo](progress/2026-06-05-agentic-retrieval-status-quo.md)
- [SQLite / Neo4j Status Quo](progress/2026-06-05-sqlite-neo4j-status-quo.md)
- [Antigravity CLI Runner Integration Report](progress/2026-06-05-antigravity-cli-runner-integration-report.md)
- [Antigravity CLI Integration Status Quo](progress/2026-06-06-antigravity-cli-integration-status-quo.md)
- [Runner Session Metadata Status Quo](progress/2026-06-06-runner-session-metadata-status-quo.md)
- [Retrieval Semantic Quality Status Quo](progress/2026-06-06-retrieval-semantic-quality-status-quo.md)
- [Cross-Session / Multilingual Retrieval Epic](progress/2026-06-07-multilingual-cross-session-retrieval-epic.md)
- [Entity And Relation Extraction Findings](progress/2026-06-08-entity-relation-extraction-findings.md)
- [Installation Hardening / Runner Guide](progress/2026-06-08-installation-hardening-and-runner-guide.md)
- [Monitor Control And Editing UI Polish](progress/2026-06-08-monitor-control-and-editing-ui-polish.md)
- [Monitor Runtime Stability And Session/Dream UX Hardening](progress/2026-06-08-monitor-runtime-stability-and-session-dream-ux-hardening.md)
- [Semantic Integrity / Ontology / Graph Retrieval Epic](progress/2026-06-08-semantic-integrity-and-ontology-epic.md)
- [SQLite Lock Hardening And Stale Dream Recovery](progress/2026-06-16-sqlite-lock-hardening-and-stale-dream-recovery.md)
- [Dream Tokens Optimization TODO](dream-tokens-optimization-todo.md)
- [Integration Management Agent Guide](skills/integration-management-agent.md)
- [Dream Pipeline v2 Runbook](runbooks/dream-pipeline-v2.md)
- [Integration Management Runbook](runbooks/integration-management.md)
- [Monitor Operator Workflows](runbooks/monitor-operator-workflows.md)
- [Platform Extension Protocol](runbooks/platform-extension-protocol.md)
- [Test Strategy And Validation Status](runbooks/test-strategy-and-validation-status.md)
- [Runner And Harness Guide](setup/RUNNER_HARNESSES.md)
- [Windows Installation Flow](setup/WINDOWS_INSTALLATION.md)
- [Instance Isolation / Workspace Binding Epic](epics/instance-isolation-and-workspace-binding-plan.md)
- [Platform Capability And Agent Flow Refactor Epic](epics/platform-capability-agent-flow-refactor-plan.md)
- [Platform Capability And Agent Flow Refactor Findings Baseline (2026-06-25)](epics/platform-capability-agent-flow-refactor-findings-2026-06-25.md)

## Archive

Historische Dokumente, die nicht mehr als aktive Referenz dienen, liegen in `docs/archive`.

- [Archive Index](archive/README.md)
- [Archived Architecture Docs](archive/architecture/)
- [Archived Progress Docs](archive/progress/)
- [Archived Roadmap Docs](archive/roadmap/)

Schnellsuche für veraltete Dokumente:

```sh
rg --files docs/archive | rg '\.md$'
```

## Spec-Driven Development

Use `.spec.md` files as the local source of truth for non-trivial boundaries:
domain concepts, application use cases, interfaces, adapters, and monitor
features. Do not create per-file specs for trivial helpers.

Exploratory lookup:

```sh
rg --files | rg '\.spec\.md$'
```

When a new `.spec.md` is added or moved, update this index with:

```sh
python3 scripts/update_docs_index.py
```

The repository check verifies this with:

```sh
python3 scripts/update_docs_index.py --check
```

<!-- spec-index:start -->

### Frontend features
- [Spec: Monitor Diagnostics Feature](../frontend/src/features/diagnostics/diagnostics.spec.md) - `frontend/src/features/diagnostics/diagnostics.spec.md`
- [Spec: Monitor Dreams Feature](../frontend/src/features/dreams/dreams.spec.md) - `frontend/src/features/dreams/dreams.spec.md`
- [Spec: Monitor Firewall Feature](../frontend/src/features/firewall/firewall.spec.md) - `frontend/src/features/firewall/firewall.spec.md`
- [Spec: Monitor Graph Feature](../frontend/src/features/graph/graph.spec.md) - `frontend/src/features/graph/graph.spec.md`
- [Spec: Monitor Howto Feature](../frontend/src/features/howto/howto.spec.md) - `frontend/src/features/howto/howto.spec.md`
- [Spec: Monitor Integrations Feature](../frontend/src/features/integrations/integrations.spec.md) - `frontend/src/features/integrations/integrations.spec.md`
- [Spec: Monitor Risk Feature](../frontend/src/features/risk/risk.spec.md) - `frontend/src/features/risk/risk.spec.md`
- [Spec: Monitor Sessions Feature](../frontend/src/features/sessions/sessions.spec.md) - `frontend/src/features/sessions/sessions.spec.md`
- [Spec: Monitor Statistics Feature](../frontend/src/features/statistics/statistics.spec.md) - `frontend/src/features/statistics/statistics.spec.md`
- [Spec: Monitor Status Feature](../frontend/src/features/status/status.spec.md) - `frontend/src/features/status/status.spec.md`
- [Spec: Monitor Storage Feature](../frontend/src/features/storage/storage.spec.md) - `frontend/src/features/storage/storage.spec.md`

### Other
- [Spec: Runner Adapter Boundary](../backend/src/agent_context_engine/adapters/runners/runners.spec.md) - `backend/src/agent_context_engine/adapters/runners/runners.spec.md`
- [Spec: SQLite Adapter Boundary](../backend/src/agent_context_engine/adapters/sqlite/sqlite.spec.md) - `backend/src/agent_context_engine/adapters/sqlite/sqlite.spec.md`
- [Windows Adapter Boundary](../backend/src/agent_context_engine/adapters/windows/windows.spec.md) - `backend/src/agent_context_engine/adapters/windows/windows.spec.md`
- [Spec: Agent Flow Application Boundary](../backend/src/agent_context_engine/application/agent_flow/agent_flow.spec.md) - `backend/src/agent_context_engine/application/agent_flow/agent_flow.spec.md`
- [Spec: Dreaming Application Boundary](../backend/src/agent_context_engine/application/dreaming/dreaming.spec.md) - `backend/src/agent_context_engine/application/dreaming/dreaming.spec.md`
- [Spec: Normalization Learning](../backend/src/agent_context_engine/application/dreaming/normalization-learning.spec.md) - `backend/src/agent_context_engine/application/dreaming/normalization-learning.spec.md`
- [Spec: Dream Semantic Normalization](../backend/src/agent_context_engine/application/dreaming/semantic-normalization.spec.md) - `backend/src/agent_context_engine/application/dreaming/semantic-normalization.spec.md`
- [Spec: Firewall Application Boundary](../backend/src/agent_context_engine/application/firewall.spec.md) - `backend/src/agent_context_engine/application/firewall.spec.md`
- [Spec: Graph Application Boundary](../backend/src/agent_context_engine/application/graph/graph.spec.md) - `backend/src/agent_context_engine/application/graph/graph.spec.md`
- [Spec: Graphing Engine Boundary](../backend/src/agent_context_engine/application/graphing/graphing.spec.md) - `backend/src/agent_context_engine/application/graphing/graphing.spec.md`
- [Spec: Hook And Wrapper Rendering Application Boundary](../backend/src/agent_context_engine/application/hook_rendering/hook_rendering.spec.md) - `backend/src/agent_context_engine/application/hook_rendering/hook_rendering.spec.md`
- [Spec: Integration Management Application Boundary](../backend/src/agent_context_engine/application/integrations.spec.md) - `backend/src/agent_context_engine/application/integrations.spec.md`
- [Spec: Platform Capability Application Boundary](../backend/src/agent_context_engine/application/platform/platform.spec.md) - `backend/src/agent_context_engine/application/platform/platform.spec.md`
- [Spec: Retrieval Application Boundary](../backend/src/agent_context_engine/application/retrieval.spec.md) - `backend/src/agent_context_engine/application/retrieval.spec.md`
- [Spec: Risk Review Application Boundary](../backend/src/agent_context_engine/application/risk_api.spec.md) - `backend/src/agent_context_engine/application/risk_api.spec.md`
- [Spec: Scheduler Application Boundary](../backend/src/agent_context_engine/application/scheduler.spec.md) - `backend/src/agent_context_engine/application/scheduler.spec.md`
- [Spec: Wrapper Publication Application Boundary](../backend/src/agent_context_engine/application/wrapper_publication/wrapper_publication.spec.md) - `backend/src/agent_context_engine/application/wrapper_publication/wrapper_publication.spec.md`
- [Spec: Graph Domain Boundary](../backend/src/agent_context_engine/domain/graph.spec.md) - `backend/src/agent_context_engine/domain/graph.spec.md`
- [Spec: Risk Domain Boundary](../backend/src/agent_context_engine/domain/risk.spec.md) - `backend/src/agent_context_engine/domain/risk.spec.md`
- [Spec: Semantic Normalization Domain](../backend/src/agent_context_engine/domain/semantic_normalization.spec.md) - `backend/src/agent_context_engine/domain/semantic_normalization.spec.md`
- [Spec: CLI Interface Boundary](../backend/src/agent_context_engine/interfaces/cli/cli.spec.md) - `backend/src/agent_context_engine/interfaces/cli/cli.spec.md`
- [Spec: Hook Interface Boundary](../backend/src/agent_context_engine/interfaces/hooks/hooks.spec.md) - `backend/src/agent_context_engine/interfaces/hooks/hooks.spec.md`
- [Spec: HTTP Monitor Interface Boundary](../backend/src/agent_context_engine/interfaces/http/http.spec.md) - `backend/src/agent_context_engine/interfaces/http/http.spec.md`
- [Spec: Ports Boundary](../backend/src/agent_context_engine/ports/ports.spec.md) - `backend/src/agent_context_engine/ports/ports.spec.md`
- [Spec: Monitor OpenAPI Contract](../contracts/openapi.spec.md) - `contracts/openapi.spec.md`
- [Spec: Monitor App Shell](../frontend/src/app/app.spec.md) - `frontend/src/app/app.spec.md`
- [Spec: Frontend Shared API Boundary](../frontend/src/shared/api/api.spec.md) - `frontend/src/shared/api/api.spec.md`

<!-- spec-index:end -->
